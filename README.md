# YouTube Assistant

## Problem Description

In the era of abundant video content on YouTube, users often struggle to efficiently extract specific information or insights from lengthy videos without watching them in their entirety. This challenge is particularly acute when dealing with educational content, tutorials, or informative videos where key points may be scattered throughout the video's duration.

The YouTube Assistant project addresses this problem by providing a Retrieval-Augmented Generation (RAG) application that allows users to interact with and query video transcripts directly. This solution enables users to quickly access relevant information from YouTube videos without the need to watch them completely, saving time and improving the efficiency of information retrieval from video content.

## Data

The YouTube Assistant utilizes data pulled in real-time using the YouTube Data API v3. This data is then processed and stored in two databases:

1. SQLite database: For structured data storage
2. Elasticsearch vector database: For efficient similarity searches on embedded text

### Data Schema

The main columns in our data structure are:

```json
{
    "content": {"type": "text"},
    "video_id": {"type": "keyword"},
    "segment_id": {"type": "keyword"},
    "start_time": {"type": "float"},
    "duration": {"type": "float"},
    "title": {"type": "text"},
    "author": {"type": "keyword"},
    "upload_date": {"type": "date"},
    "view_count": {"type": "integer"},
    "like_count": {"type": "integer"},
    "comment_count": {"type": "integer"},
    "video_duration": {"type": "text"}
}
```

This schema allows for comprehensive storage of video metadata alongside the transcript content, enabling rich querying and analysis capabilities.

## Functionality

The YouTube Assistant offers the following key features:

1. **Real-time Data Extraction**: Utilizes the YouTube Data API v3 to fetch video data and transcripts on-demand.

2. **Efficient Data Storage**: Stores structured data in SQLite and uses Elasticsearch for vector embeddings, allowing for fast retrieval and similarity searches.

3. **Interactive Querying**: Provides a chat interface where users can ask questions about the video transcripts that have been downloaded or extracted in real-time.

4. **Contextual Understanding**: Leverages RAG technology to understand the context of user queries and provide relevant information from the video transcripts.

5. **Metadata Analysis**: Allows users to query not just the content of the videos but also metadata such as view counts, likes, and upload dates.

6. **Time-stamped Responses**: Can provide information about specific segments of videos, including start times and durations.

By combining these features, the YouTube Assistant empowers users to efficiently extract insights and information from YouTube videos without the need to watch them in full, significantly enhancing the way people interact with and learn from video content.

## Project Structure

The YouTube Assistant project is organized as follows:

```
youtube-rag-app/
├── app/
│   ├── main.py
│   ├── ui.py
│   ├── transcript_extractor.py
│   ├── data_processor.py
│   ├── elasticsearch_handler.py
│   ├── database.py
│   ├── rag.py
│   ├── query_rewriter.py
│   └── evaluation.py
├── data/
│   └── sqlite.db
├── config/
│   └── config.yaml
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

### Directory and File Descriptions:

- `app/`: Contains the main application code
  - `main.py`: Entry point of the application
  - `ui.py`: Handles the user interface
  - `transcript_extractor.py`: Manages YouTube transcript extraction
  - `data_processor.py`: Processes and prepares data for storage and analysis
  - `elasticsearch_handler.py`: Manages interactions with Elasticsearch
  - `database.py`: Handles SQLite database operations
  - `rag.py`: Implements the Retrieval-Augmented Generation logic
  - `query_rewriter.py`: Refines and optimizes user queries
  - `evaluation.py`: Contains evaluation metrics and functions
- `data/`: Stores the SQLite database
- `config/`: Contains configuration files
- `requirements.txt`: Lists all Python dependencies
- `Dockerfile`: Defines the Docker image for the application
- `docker-compose.yml`: Orchestrates the application and its services

## Getting Started

git clone git@github.com:ganesh3/rag-youtube-assistant.git
run-docker-compose-windows.ps1

## License
GPL v3
