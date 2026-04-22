import requests
import pandas as pd


def extract_api():
    url = "https://saddam-teacher-api.onrender.com/utilities/clean?token=saddam_teacher"
    response = requests.get(url)
    data = response.json()
    return data

def extract_excel():
    data = pd.read_excel("Logistics_500.xlsx")
    return data