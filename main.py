# ==================================================================
#         main.py - VERSI FINAL v2 (FIX NameError JRA_LABELS)
# ==================================================================

import os
import io
import time
import requests
import pandas as pd
# Dask sudah tidak kita gunakan
from dotenv import load_dotenv
from flask import Flask, request, render_template, send_file

# Memuat variabel rahasia
load_dotenv() 

# --- KONFIGURASI GLOBAL ---
HF_API_KEY = os.getenv("HF_API_KEY")
API_URL = "https://api-inference.huggingface.co/models/facebook/bart-large-mnli"
HEADERS = {"Authorization": f"Bearer {HF_API_KEY}"}
JRA_FILE_PATH = "JRA.xlsx - Sheet1.csv"

# --- FUNGSI INTI (DENGAN PERBAIKAN) ---
# Fungsi ini sekarang menggunakan 'jra_labels' (huruf kecil) yang diterima
def classify_title(title: str, jra_labels: list):
    """Mengirim judul ke Hugging Face API untuk klasifikasi Zero-Shot."""
    # MENGGUNAKAN VARIABEL YANG BENAR (jra_labels)
    if not jra_labels:
        return "Klasifikasi gagal, pedoman JRA kosong."
    
    # MENGGUNAKAN VARIABEL YANG BENAR (jra_labels)
    payload = { "inputs": title, "parameters": {"candidate_labels": jra_labels} }
    try:
        response = requests.post(API_URL, headers=HEADERS, json=payload, timeout=180)
        response.raise_for_status() 
        result = response.json()
        if isinstance(result, dict) and result.get("error"):
            if "is currently loading" in result.get("error", ""):
                time.sleep(15)
                print("Retrying after model loading...")
                response = requests.post(API_URL, headers=HEADERS, json=payload, timeout=180)
                response.raise_for_status()
                result = response.json()
        return result[0]['label']
    except requests.exceptions.Timeout:
        return "Error: Timeout ke server AI"
    except requests.exceptions.RequestException as e:
        return f"Error Koneksi API"
    except (KeyError, IndexError, TypeError):
        return "Error: Format respon API salah"

def get_jra_details(klasifikasi_lengkap: str, jra_df: pd.DataFrame):
    if jra_df is None: return "N/A", "N/A", "DataFrame Pedoman tidak dimuat"
    try:
        kode_jra = klasifikasi_lengkap.split()[0]
        detail = jra_df.loc[kode_jra]
        return detail['Retensi Aktif'], detail['Retensi Inaktif'], detail['Keterangan']
    except (KeyError, IndexError):
        return "N/A", "N/A", "Tidak Ditemukan di Pedoman"

# --- SETUP APLIKASI FLASK ---
app = Flask(__name__)

# --- ENDPOINTS (ROUTE) ---
@app.route("/")
def read_root():
    return render_template("index.html")

@app.route("/process-file/", methods=['POST'])
def process_file():
    if 'file' not in request.files: return "Error: Tidak ada file yang diunggah.", 400
    uploaded_file = request.files['file']
    if uploaded_file.filename == '': return "Error: Tidak ada file yang dipilih.", 400

    try:
        column_names = ["Kode", "Uraian", "Retensi Aktif", "Retensi Inaktif", "Keterangan"]
        jra_details_df = pd.read_csv(
            JRA_FILE_PATH, engine='python', header=None, names=column_names
        )
        jra_details_df.set_index('Kode', inplace=True)
        jra_labels = (jra_details_df.index + " " + jra_details_df['Uraian']).tolist()
    except Exception as e:
        return f"Error Kritis: Gagal memuat file pedoman JRA. Error: {e}", 500

    temp_path = f"temp_{uploaded_file.filename}"
    try:
        uploaded_file.save(temp_path)
        df_to_process = pd.read_excel(temp_path, engine='openpyxl')
        if 'Judul Dokumen' not in df_to_process.columns:
            raise ValueError("File Excel harus memiliki kolom bernama 'Judul Dokumen'")
            
        df_to_process['Klasifikasi'] = df_to_process['Judul Dokumen'].apply(
            lambda title: (time.sleep(0.1), classify_title(str(title), jra_labels=jra_labels))[1]
        )
        result_df = df_to_process
        
        result_df[['Aktif', 'Inaktif', 'Keterangan']] = result_df['Klasifikasi'].apply(
            lambda x: pd.Series(get_jra_details(x, jra_df=jra_details_df))
        )

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            result_df.to_excel(writer, index=False, sheet_name='Hasil Klasifikasi')
        output.seek(0)

        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f"hasil_klasifikasi_{uploaded_file.filename}"
        )
    except Exception as e:
        return f"Terjadi error saat memproses file Anda: {e}", 500
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)