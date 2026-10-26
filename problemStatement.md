# AI-Powered Restaurant Recommendation System (Zomato Use Case)

## Overview

Build an AI-powered restaurant recommendation service inspired by Zomato. The system intelligently suggests restaurants based on user preferences by combining structured data with a Large Language Model (LLM).

## Objective

Design and implement an application that:

- Takes user preferences (such as location, budget, cuisine, and ratings)
- Uses a real-world dataset of restaurants
- Leverages an LLM to generate personalized, human-like recommendations
- Displays clear and useful results to the user

## System Workflow

### 1. Data Ingestion

- Load and preprocess the Zomato dataset from Hugging Face: [ManikaSaini/zomato-restaurant-recommendation](https://huggingface.co/datasets/ManikaSaini/zomato-restaurant-recommendation)
- Extract relevant fields such as restaurant name, location, cuisine, cost, rating, and related attributes

### 2. User Input

Collect user preferences:

| Preference | Examples |
| --- | --- |
| Location | Delhi, Bangalore |
| Budget | Low, medium, high |
| Cuisine | Italian, Chinese |
| Minimum rating | User-specified threshold |
| Additional preferences | Family-friendly, quick service |

### 3. Integration Layer

- Filter and prepare relevant restaurant data based on user input
- Pass structured results into an LLM prompt
- Design a prompt that helps the LLM reason and rank options

### 4. Recommendation Engine

Use the LLM to:

- Rank restaurants
- Provide explanations for why each recommendation fits
- Optionally summarize the choices

### 5. Output Display

Present the top recommendations in a user-friendly format. Each result includes:

- Restaurant name
- Cuisine
- Rating
- Estimated cost
- AI-generated explanation

## End-to-End Flow

```text
Zomato dataset (Hugging Face)
        |
        v
Load and preprocess restaurant records
        |
        v
User preferences (location, budget, cuisine, rating, extras)
        |
        v
Filter and structure matching restaurants
        |
        v
LLM prompt: reason, rank, and explain
        |
        v
Top recommendations with name, cuisine, rating, cost, and explanation
```
