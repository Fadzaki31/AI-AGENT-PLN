# ==================================================================
#            main.py - VERSI FINAL (DISEMPURNAKAN TANPA DASK)
# ==================================================================

import os
import io
import time
import requests
import pandas as pd
# import dask.dataframe as dd <-- HAPUS DASK
from dotenv import load_dotenv
from flask import Flask, request, render_template, send_file

# Memuat variabel rahasia
load_dotenv() 

# --- KONFIGURASI GLOBAL (TIDAK BERUBAH) ---
HF_API_KEY = os.getenv("HF_API_KEY")
API_URL = "https://api-inference.huggingface.co/models/facebook/bart-large-mnli"
HEADERS = {"Authorization": f"Bearer {HF_API_KEY}"}

# --- MEMUAT PEDOMAN JRA (TIDAK BERUBAH) ---
JRA_FILE_PATH = "/home/fadzaki/ai-agent-pln/JRA.xlsx - Sheet1.csv"
JRA_LABELS = []
JRA_DETAILS_DF = None

try:
    column_names = ["Kode", "Uraian", "Retensi Aktif", "Retensi Inaktif", "Keterangan"]
    JRA_DETAILS_DF = pd.read_csv(
        JRA_FILE_PATH, engine='python', header=None, names=column_names
    )
    JRA_DETAILS_DF.set_index('Kode', inplace=True)
    JRA_LABELS = (JRA_DETAILS_DF.index + " " + JRA_DETAILS_DF['Uraian']).tolist()
    print("SUCCESS: Pedoman JRA berhasil dimuat.")
except Exception as e:
    print(f"FATAL ERROR saat memproses file JRA: {e}")
    JRA_LABELS = ["ERROR: Gagal memproses file JRA"]

# --- FUNGSI INTI (TIDAK BERUBAH) ---
def classify_title(title: str):
    if not JRA_LABELS or "ERROR" in JRA_LABELS[0]:
        return "Klasifikasi tidak bisa dilakukan, pedoman JRA tidak dimuat."
    payload = { "inputs": title, "parameters": {"candidate_labels": JRA_LABELS} }
    try:
        response = requests.post(API_URL, headers=HEADERS, json=payload, timeout=20)
        response.raise_for_status() 
        result = response.json()
        return result['labels'][0]
    except Exception as e:
        return f"Error Klasifikasi API: {e}"

def get_jra_details(klasifikasi_lengkap: str):
    if JRA_DETAILS_DF is None: return "N/A", "N/A", "DataFrame Pedoman tidak dimuat"
    try:
        kode_jra = klasifikasi_lengkap.split()[0]
        detail = JRA_DETAILS_DF.loc[kode_jra]
        return detail['Retensi Aktif'], detail['Retensi Inaktif'], detail['Keterangan']
    except (KeyError, IndexError):
        return "N/A", "N/A", "Tidak Ditemukan di Pedoman"

# --- SETUP APLIKASI FLASK (TIDAK BERUBAH) ---
app = Flask(__name__)

# --- ENDPOINTS (ROUTE) ---
@app.route("/")
def read_root():
    return render_template("index.html")

@app.route("/process-file/", methods=['POST'])
def process_file():
    if 'file' not in request.files: return "Error: Tidak ada file yang diunggah.", 400
    file = request.files['file']
    if file.filename == '': return "Error: Tidak ada file yang dipilih.", 400

    temp_path = f"temp_{file.filename}"
    try:
        file.save(temp_path)
        df = pd.read_excel(temp_path, engine='openpyxl')
        if 'Judul Dokumen' not in df.columns:
            raise ValueError("File Excel harus memiliki kolom bernama 'Judul Dokumen'")
            
        # --- BLOK DASK DIHAPUS ---
        # ddf = dd.from_pandas(df, npartitions=4)
        # def classify_partition(...): ...
        # result_ddf = ddf.map_partitions(...)
        # result_df = result_ddf.compute()
        # --- AKHIR BLOK DASK YANG DIHAPUS ---

        # --- DIGANTIKAN DENGAN PROSES PANDAS YANG LEBIH SEDERHANA ---
        # Langsung terapkan fungsi classify_title ke DataFrame pandas
        # Ini akan memproses baris per baris secara sekuensial
        df['Klasifikasi'] = df['Judul Dokumen'].apply(
            lambda title: (time.sleep(0.1), classify_title(str(title)))[1]
        )
        result_df = df # DataFrame hasil adalah df yang sudah kita modifikasi
        # --- AKHIR DARI BLOK PENGGANTI ---

        result_df[['Aktif', 'Inaktif', 'Keterangan']] = result_df['Klasifikasi'].apply(
            lambda x: pd.Series(get_jra_details(x))
        )

        output = io.BytesIO()
        writer = pd.ExcelWriter(output, engine='openpyxl')
        result_df.to_excel(writer, index=False, sheet_name='Hasil Klasifikasi')
        writer.close()
        output.seek(0)

        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f"hasil_klasifikasi_{file.filename}"
        )
    except ValueError as e:
        return {"error": str(e)}
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)