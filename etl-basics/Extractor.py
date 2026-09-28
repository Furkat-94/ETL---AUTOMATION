import os
from pathlib import Path

import requests
import pandas as pd
from dotenv import load_dotenv

# Адрес API вместе с токеном — в .env в корне репозитория (API_URL)
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def extract_api():
    url = os.getenv("API_URL")
    response = requests.get(url)
    data = response.json()
    return data

def extract_excel():
    data = pd.read_excel("Logistics_500.xlsx")
    return data