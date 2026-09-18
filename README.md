# Bharat Talaash

AI-assisted missing-person search and matching platform built using AWS.

## Architecture

Frontend
→ API Gateway
→ AWS Lambda
→ Amazon Bedrock
→ CPU Matching Service
→ DynamoDB FoundReport

Background ingestion:

ZIPNET Scraper
→ DynamoDB
→ Amazon SQS
→ Embedding Dispatcher
→ GPU Controller
→ NVIDIA T4 EC2
→ SentenceTransformer Embeddings
→ CPU Matcher Refresh

## Components

### Lambda
AWS Lambda functions for search, missing case creation, monitoring and embedding orchestration.

### Matcher
Production CPU matching engine and FastAPI service.

### Embeddings
GPU embedding generation using sentence-transformers/all-MiniLM-L6-v2.

### Scraper
ZIPNET unidentified-person ingestion pipeline.

### GPU
GPU execution jobs and embedding workers.

### Infrastructure
EC2 and service configuration.

## Search Model

The system combines semantic similarity with structured evidence such as:

- age
- gender
- location
- clothing
- physical description
- distinctive marks

Returned results are potential matches and require human verification.

## Technology

- AWS Lambda
- Amazon API Gateway
- Amazon Bedrock
- Amazon DynamoDB
- Amazon SQS
- Amazon EC2
- AWS Systems Manager
- Amazon EventBridge
- Amazon S3
- Amazon Transcribe
- FastAPI
- Sentence Transformers
- PyTorch
- Python

## Disclaimer

Similarity scores are candidate-ranking signals and must not be treated as identity confirmation.
