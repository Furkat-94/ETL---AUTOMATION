from Extractor import extract_api
from Transforming import transform
from Loading import load_to_excel, load_to_sql


def automation():
    data = extract_api()
    df = transform(data)
    load = load_to_sql(df)

print("Successful !")
if __name__ == "__main__":
    automation()