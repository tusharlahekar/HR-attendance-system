"""
Loads the sample documents from sample_data/ into your database.
Usage: python sample_seed.py
"""
import os
import pathlib
from bson import json_util
from dotenv import load_dotenv
from pymongo import MongoClient

# 1. Load environment variables from .env file
load_dotenv()

# 2. Setup paths
# Assumes sample_data/ folder is in the same directory as this script
here = pathlib.Path(__file__).parent / "sample_data"

# 3. Setup MongoDB Connection
# Reads MONGO_URI and MONGO_DB from .env; defaults to local if not found
mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
db_name = os.getenv("MONGO_DB", "attendance_db")

client = MongoClient(mongo_uri, tz_aware=True)
db = client[db_name]

def seed_database():
    # The two collections defined in DATA_MODEL.md
    collections = ["employees", "attendance_logs"]

    for name in collections:
        file_path = here / f"{name}.json"
        
        if not file_path.exists():
            print(f"Skipping {name}: File not found at {file_path}")
            continue

        # Load the JSON data
        # Note: We use json_util because MongoDB exports often use special 
        # formats like {"$date": ...} which standard json library can't parse correctly.
        with open(file_path, "r") as f:
            docs = json_util.loads(f.read())

        # Clear existing data to ensure a clean state
        db[name].delete_many({})
        
        # Insert the documents
        if docs:
            db[name].insert_many(docs)
            print(f"Successfully loaded {len(docs):>2} documents into '{db_name}.{name}'")
        else:
            print(f"No documents found in {file_path}")

if __name__ == "__main__":
    try:
        # Check connection
        client.admin.command('ping')
        print("Connected to MongoDB successfully.")
        seed_database()
        print("\nSeeding complete. You can now run the FastAPI app.")
    except Exception as e:
        print(f"Error connecting to MongoDB: {e}")