import streamlit as st
import pandas as pd
from transcript_extractor import extract_video_id, get_transcript, get_channel_videos, process_videos
from data_processor import DataProcessor
from database import DatabaseHandler
from rag import RAGSystem
from query_rewriter import QueryRewriter
from evaluation import EvaluationSystem
from sentence_transformers import SentenceTransformer
import os
import json
import requests
from tqdm import tqdm
import sqlite3
import logging
import ollama

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@st.cache_resource
def init_components():
    try:
        db_handler = DatabaseHandler()
        data_processor = DataProcessor()
        rag_system = RAGSystem(data_processor)
        query_rewriter = QueryRewriter()
        evaluation_system = EvaluationSystem(data_processor, db_handler)
        logger.info("Components initialized successfully")
        return db_handler, data_processor, rag_system, query_rewriter, evaluation_system
    except Exception as e:
        logger.error(f"Error initializing components: {str(e)}")
        st.error(f"Error initializing components: {str(e)}")
        st.error("Please check your configuration and ensure all services are running.")
        return None, None, None, None, None
        
components = init_components()
if components:
    db_handler, data_processor, rag_system, query_rewriter, evaluation_system = components
else:
    st.stop()

# Ground Truth Generation

def generate_questions(transcript):
    prompt_template = """
    You are an AI assistant tasked with generating questions based on a YouTube video transcript.
    Formulate atleast 10 questions that a user might ask based on the provided transcript.
    Make the questions specific to the content of the transcript.
    The questions should be complete and not too short. Use as few words as possible from the transcript.
    It is important that the questions are relevant to the content of the transcript and are atleast 10 in number.

    The transcript:

    {transcript}

    Provide the output in parsable JSON without using code blocks:

    {{"questions": ["question1", "question2", ..., "question10"]}}
    """.strip()

    prompt = prompt_template.format(transcript=transcript)

    try:
        response = ollama.chat(
            model='phi3.5',
            messages=[{"role": "user", "content": prompt}]
        )
        print("Printing the response from OLLAMA: " + response['message']['content'])
        return json.loads(response['message']['content'])
    except Exception as e:
        logger.error(f"Error generating questions: {str(e)}")
        return None
    
def generate_ground_truth(video_id=None, existing_transcript=None):
    if video_id is None and existing_transcript is None:
        st.error("Please provide either a video ID or an existing transcript.")
        return None

    if video_id:
        transcript_data = get_transcript(video_id)
        if transcript_data and 'transcript' in transcript_data:
            full_transcript = " ".join([entry['text'] for entry in transcript_data['transcript']])
        else:
            logger.error("Failed to retrieve transcript for the provided video ID.")
            st.error("Failed to retrieve transcript for the provided video ID.")
            return None
    else:
        full_transcript = existing_transcript

    questions = generate_questions(full_transcript)
    
    if questions and 'questions' in questions:
        df = pd.DataFrame([(video_id if video_id else "custom", q) for q in questions['questions']], columns=['video_id', 'question'])
        
        os.makedirs('data', exist_ok=True)
        df.to_csv('data/ground-truth-retrieval.csv', index=False)
        st.success("Ground truth data generated and saved to data/ground-truth-retrieval.csv")
        return df
    else:
        logger.error("Failed to generate questions.")
        st.error("Failed to generate questions.")
    return None

# RAG Evaluation
def evaluate_rag(sample_size=200):
    try:
        ground_truth = pd.read_csv('data/ground-truth-retrieval.csv')
    except FileNotFoundError:
        logger.error("Ground truth file not found. Please generate ground truth data first.")
        st.error("Ground truth file not found. Please generate ground truth data first.")
        return None

    sample = ground_truth.sample(n=min(sample_size, len(ground_truth)), random_state=1)
    evaluations = []
    
    prompt_template = """
    You are an expert evaluator for a Youtube transcript assistant.
    Your task is to analyze the relevance of the generated answer to the given question.
    Based on the relevance of the generated answer, you will classify it
    as "NON_RELEVANT", "PARTLY_RELEVANT", or "RELEVANT".

    Here is the data for evaluation:

    Question: {question}
    Generated Answer: {answer_llm}

    Please analyze the content and context of the generated answer in relation to the question
    and provide your evaluation in parsable JSON without using code blocks:

    {{
      "Relevance": "NON_RELEVANT" | "PARTLY_RELEVANT" | "RELEVANT",
      "Explanation": "[Provide a brief explanation for your evaluation]"
    }}
    """.strip()

    progress_bar = st.progress(0)
    for i, (_, row) in enumerate(sample.iterrows()):
        question = row['question']
        video_id = row['video_id']
        
        # Get the index name for the video (you might need to adjust this based on your setup)
        index_name = db_handler.get_elasticsearch_index_by_youtube_id(video_id, "all-MiniLM-L6-v2")  # Assuming you're using this embedding model
        
        if not index_name:
            logger.warning(f"No index found for video {video_id}. Skipping this question.")
            continue

        try:
            answer_llm, _ = rag_system.query(question, index_name=index_name)
        except ValueError as e:
            logger.error(f"Error querying RAG system: {str(e)}")
            continue

        prompt = prompt_template.format(question=question, answer_llm=answer_llm)
        try:
            response = ollama.chat(
                model='phi3.5',
                messages=[{"role": "user", "content": prompt}]
            )
            evaluation_json = json.loads(response['message']['content'])
            evaluations.append((
                str(video_id),
                str(question),
                str(answer_llm),
                str(evaluation_json.get('Relevance', 'UNKNOWN')),
                str(evaluation_json.get('Explanation', 'No explanation provided'))
            ))
        except Exception as e:
            logger.warning(f"Failed to evaluate question: {question}. Error: {str(e)}")
            st.warning(f"Failed to evaluate question: {question}")
        progress_bar.progress((i + 1) / len(sample))

    # Store RAG evaluations in the database
    conn = sqlite3.connect('data/sqlite.db')
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS rag_evaluations (
        video_id TEXT,
        question TEXT,
        answer TEXT,
        relevance TEXT,
        explanation TEXT
    )
    ''')
    cursor.executemany('''
    INSERT INTO rag_evaluations (video_id, question, answer, relevance, explanation)
    VALUES (?, ?, ?, ?, ?)
    ''', evaluations)
    conn.commit()
    conn.close()

    logger.info("Evaluation complete. Results stored in the database.")
    st.success("Evaluation complete. Results stored in the database.")
    return evaluations

@st.cache_data
def process_single_video(video_id, embedding_model):
    # Check if the video has already been processed with the current embedding model
    existing_index = db_handler.get_elasticsearch_index_by_youtube_id(video_id, embedding_model)
    if existing_index:
        logger.info(f"Video {video_id} has already been processed with {embedding_model}. Using existing index: {existing_index}")
        return existing_index

    transcript_data = get_transcript(video_id)
    if transcript_data is None:
        logger.error(f"Failed to retrieve transcript for video {video_id}")
        return None

    # Store video metadata in the database
    video_data = {
        'video_id': video_id,
        'title': transcript_data['metadata'].get('title', 'Unknown Title'),
        'author': transcript_data['metadata'].get('author', 'Unknown Author'),
        'upload_date': transcript_data['metadata'].get('upload_date', 'Unknown Date'),
        'view_count': int(transcript_data['metadata'].get('view_count', 0)),
        'like_count': int(transcript_data['metadata'].get('like_count', 0)),
        'comment_count': int(transcript_data['metadata'].get('comment_count', 0)),
        'video_duration': transcript_data['metadata'].get('duration', 'Unknown Duration')
    }
    try:
        db_handler.add_video(video_data)
    except Exception as e:
        logger.error(f"Error adding video to database: {str(e)}")
        return None

    # Process transcript for RAG system
    try:
        data_processor.process_transcript(video_id, transcript_data)
    except Exception as e:
        logger.error(f"Error processing transcript: {str(e)}")
        return None
    
    # Create Elasticsearch index
    index_name = f"video_{video_id}_{embedding_model}".lower()
    try:
        index_name = data_processor.build_index(index_name)
        logger.info(f"Successfully built index: {index_name}")
    except Exception as e:
        logger.error(f"Error building index: {str(e)}")
        return None
    
    # Add embedding model to the database
    embedding_model_id = db_handler.add_embedding_model(embedding_model, "Description of the model")
    
    # Get the video ID from the database
    video_db_record = db_handler.get_video_by_youtube_id(video_id)
    if video_db_record is None:
        logger.error(f"Failed to retrieve video record from database for video {video_id}")
        return None
    video_db_id = video_db_record[0]  # Assuming the ID is the first column
    
    # Store Elasticsearch index information
    db_handler.add_elasticsearch_index(video_db_id, index_name, embedding_model_id)
    
    logger.info(f"Processed and indexed transcript for video {video_id}")
    return index_name

@st.cache_data
def process_multiple_videos(video_ids, embedding_model):
    indices = []
    for video_id in video_ids:
        index = process_single_video(video_id, embedding_model)
        if index:
            indices.append(index)
    logger.info(f"Processed and indexed transcripts for {len(indices)} videos")
    st.success(f"Processed and indexed transcripts for {len(indices)} videos")
    return indices

def main():
    st.title("YouTube Transcript RAG System")

    components = init_components()
    if not all(components):
        st.error("Failed to initialize one or more components. Please check the logs and your configuration.")
        return

    db_handler, data_processor, rag_system, query_rewriter, evaluation_system = components

    tab1, tab2, tab3 = st.tabs(["RAG System", "Ground Truth Generation", "Evaluation"])

    with tab1:
        st.header("RAG System")
        
        # Video selection section
        st.subheader("Select a Video")
        videos = db_handler.get_all_videos()
        if not videos:
            st.warning("No videos available. Please process some videos first.")
        else:
            video_df = pd.DataFrame(videos, columns=['youtube_id', 'title', 'channel_name', 'upload_date'])
            
            # Allow filtering by channel name
            channels = sorted(video_df['channel_name'].unique())
            selected_channel = st.selectbox("Filter by Channel", ["All"] + channels)
            
            if selected_channel != "All":
                video_df = video_df[video_df['channel_name'] == selected_channel]
            
            # Display videos and allow selection
            st.dataframe(video_df)
            selected_video_id = st.selectbox("Select a Video", video_df['youtube_id'].tolist(), format_func=lambda x: video_df[video_df['youtube_id'] == x]['title'].iloc[0])
            
            # Embedding model selection
            embedding_model = st.selectbox("Select embedding model:", ["all-MiniLM-L6-v2", "all-mpnet-base-v2"])
            
            # Get the index name for the selected video and embedding model
            index_name = db_handler.get_elasticsearch_index_by_youtube_id(selected_video_id, embedding_model)
            
            if index_name:
                st.success(f"Using index: {index_name}")
            else:
                st.warning("No index found for the selected video and embedding model. The index will be built when you search.")
        
        # Process new video section
        st.subheader("Process New Video")
        input_type = st.radio("Select input type:", ["Video URL", "Channel URL", "YouTube ID"])
        input_value = st.text_input("Enter the URL or ID:")
        
        if st.button("Process"):
            with st.spinner("Processing..."):
                data_processor.embedding_model = SentenceTransformer(embedding_model)
                if input_type == "Video URL":
                    video_id = extract_video_id(input_value)
                    if video_id:
                        index_name = process_single_video(video_id, embedding_model)
                        if index_name is None:
                            st.error(f"Failed to process video {video_id}")
                        else:
                            st.success(f"Successfully processed video {video_id}")
                    else:
                        st.error("Failed to extract video ID from the URL")
                elif input_type == "Channel URL":
                    channel_videos = get_channel_videos(input_value)
                    if channel_videos:
                        index_names = process_multiple_videos([video['video_id'] for video in channel_videos], embedding_model)
                        if not index_names:
                            st.error("Failed to process any videos from the channel")
                        else:
                            st.success(f"Successfully processed {len(index_names)} videos from the channel")
                    else:
                        st.error("Failed to retrieve videos from the channel")
                else:
                    index_name = process_single_video(input_value, embedding_model)
                    if index_name is None:
                        st.error(f"Failed to process video {input_value}")
                    else:
                        st.success(f"Successfully processed video {input_value}")
        
        # Query section
        st.subheader("Query the RAG System")
        query = st.text_input("Enter your query:")
        rewrite_method = st.radio("Query rewriting method:", ["None", "Chain of Thought", "ReAct"])
        search_method = st.radio("Search method:", ["Hybrid", "Text-only", "Embedding-only"])

        if st.button("Search"):
            if not selected_video_id:
                st.error("Please select a video before searching.")
            else:
                with st.spinner("Searching..."):
                    rewritten_query = query
                    rewrite_prompt = ""
                    if rewrite_method == "Chain of Thought":
                        rewritten_query, rewrite_prompt = query_rewriter.rewrite_cot(query)
                    elif rewrite_method == "ReAct":
                        rewritten_query, rewrite_prompt = query_rewriter.rewrite_react(query)

                    st.subheader("Query Processing")
                    st.write("Original query:", query)
                    if rewrite_method != "None":
                        st.write("Rewritten query:", rewritten_query)
                        st.text_area("Query rewriting prompt:", rewrite_prompt, height=100)
                        if rewritten_query == query:
                            st.warning("Query rewriting failed. Using original query.")

                    search_method_map = {"Hybrid": "hybrid", "Text-only": "text", "Embedding-only": "embedding"}
                    try:
                        # Ensure index is built before searching
                        if not index_name:
                            st.info("Building index for the selected video...")
                            index_name = process_single_video(selected_video_id, embedding_model)
                            if not index_name:
                                st.error("Failed to build index for the selected video.")
                                return

                        response, final_prompt = rag_system.query(rewritten_query, search_method=search_method_map[search_method], index_name=index_name)
                        
                        st.subheader("RAG System Prompt")
                        if final_prompt:
                            st.text_area("Prompt sent to LLM:", final_prompt, height=300)
                        else:
                            st.warning("No prompt was generated. This might indicate an issue with the RAG system.")
                        
                        st.subheader("Response")
                        if response:
                            st.write(response)
                        else:
                            st.error("No response generated. Please try again or check the system logs for errors.")
                    except ValueError as e:
                        logger.error(f"Error during search: {str(e)}")
                        st.error(f"Error during search: {str(e)}")
                    except Exception as e:
                        logger.error(f"An unexpected error occurred: {str(e)}")
                        st.error(f"An unexpected error occurred: {str(e)}")

    with tab2:
        st.header("Ground Truth Generation")
        use_existing_transcript = st.checkbox("Use existing transcript")
        
        if use_existing_transcript:
            # Get all available videos (assuming all videos have transcripts)
            videos = db_handler.get_all_videos()
            if not videos:
                st.warning("No videos available. Please process some videos first.")
            else:
                video_df = pd.DataFrame(videos, columns=['youtube_id', 'title', 'channel_name', 'upload_date'])
                
                # Allow filtering by channel name
                channels = sorted(video_df['channel_name'].unique())
                selected_channel = st.selectbox("Filter by Channel", ["All"] + channels, key="gt_channel_filter")
                
                if selected_channel != "All":
                    video_df = video_df[video_df['channel_name'] == selected_channel]
                
                # Display videos and allow selection
                st.dataframe(video_df)
                selected_video_id = st.selectbox("Select a Video", video_df['youtube_id'].tolist(), 
                                                 format_func=lambda x: video_df[video_df['youtube_id'] == x]['title'].iloc[0],
                                                 key="gt_video_select")
                
                if st.button("Generate Ground Truth from Existing Transcript"):
                    with st.spinner("Generating ground truth..."):
                        # Retrieve the transcript content (you'll need to implement this method)
                        transcript_data = get_transcript(selected_video_id)
                        if transcript_data and 'transcript' in transcript_data:
                            full_transcript = " ".join([entry['text'] for entry in transcript_data['transcript']])
                            ground_truth_df = generate_ground_truth(video_id=selected_video_id, existing_transcript=full_transcript)
                            if ground_truth_df is not None:
                                st.dataframe(ground_truth_df)
                                csv = ground_truth_df.to_csv(index=False)
                                st.download_button(
                                    label="Download Ground Truth CSV",
                                    data=csv,
                                    file_name=f"ground_truth_{selected_video_id}.csv",
                                    mime="text/csv",
                                )
                        else:
                            st.error("Failed to retrieve transcript content.")
        else:
            video_id = st.text_input("Enter YouTube Video ID for ground truth generation:")
            if st.button("Generate Ground Truth"):
                with st.spinner("Generating ground truth..."):
                    ground_truth_df = generate_ground_truth(video_id=video_id)
                    if ground_truth_df is not None:
                        st.dataframe(ground_truth_df)
                        csv = ground_truth_df.to_csv(index=False)
                        st.download_button(
                            label="Download Ground Truth CSV",
                            data=csv,
                            file_name=f"ground_truth_{video_id}.csv",
                            mime="text/csv",
                        )

    with tab3:
        st.header("RAG Evaluation")

        # Load ground truth data
        try:
            ground_truth_df = pd.read_csv('data/ground-truth-retrieval.csv')
            ground_truth_available = True
        except FileNotFoundError:
            ground_truth_available = False

        if ground_truth_available:
            st.write("Evaluation will be run on the following ground truth data:")
            st.dataframe(ground_truth_df)
            st.info("The evaluation will use this ground truth data to assess the performance of the RAG system.")

            sample_size = st.number_input("Enter sample size for evaluation:", min_value=1, max_value=len(ground_truth_df), value=min(200, len(ground_truth_df)))
            
            if st.button("Run Evaluation"):
                with st.spinner("Running evaluation..."):
                    evaluation_results = evaluate_rag(sample_size)
                    if evaluation_results:
                        st.write("Evaluation Results:")
                        st.dataframe(pd.DataFrame(evaluation_results, columns=['Video ID', 'Question', 'Answer', 'Relevance', 'Explanation']))
        else:
            st.warning("No ground truth data available. Please generate ground truth data first.")
            st.button("Run Evaluation", disabled=True)

        # Add a section to generate ground truth if it's not available
        if not ground_truth_available:
            st.subheader("Generate Ground Truth")
            st.write("You need to generate ground truth data before running the evaluation.")
            if st.button("Go to Ground Truth Generation"):
                st.session_state.active_tab = "Ground Truth Generation"
                st.experimental_rerun()

if __name__ == "__main__":
    main()