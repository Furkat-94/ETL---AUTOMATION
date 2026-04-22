import pandas as pd


def transform(data):
    df = pd.DataFrame(data)
    df["hisoblangan_summa"] = df["hisoblangan_summa"].astype(float)
    df["tolangan_summa"] = df["tolangan_summa"].fillna(df["tolangan_summa"].median())
    return df