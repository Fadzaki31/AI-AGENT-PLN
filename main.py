import os
import io
import time
import requests
import pandas as pd
from dotenv import load_dotenv
from flask import Flask, request, render_template, send_file

# Memuat variabel rahasia dari file .env (atau Secrets di Replit)
load_dotenv() 

# --- KONFIGURASI GLOBAL ---
HF_API_KEY = os.getenv("HF_API_KEY")
# Pastikan ini adalah URL model spesialis Anda yang sudah di-fine-tuning
API_URL = "https://api-inference.huggingface.co/models/fadzaki31/jra-klasifikasi-spesialis" 
HEADERS = {"Authorization": f"Bearer {HF_API_KEY}"}
# Path ke file pedoman JRA. Gunakan path absolut untuk PythonAnywhere, atau relatif untuk Replit/Lokal.
JRA_FILE_PATH = "JRA.xlsx - Sheet1.csv" # Path untuk Replit/Lokal
# JRA_FILE_PATH = "/home/fadzaki/ai-agent-pln/JRA.xlsx - Sheet1.csv" # Path untuk PythonAnywhere

# --- FUNGSI-FUNGSI INTI ---

def classify_title(title: str):
    """Mengirim judul ke model klasifikasi fine-tuned Anda."""
    
    # Payload untuk model klasifikasi standar (bukan zero-shot)
    payload = {"inputs": title} 
    
    try:
        response = requests.post(API_URL, headers=HEADERS, json=payload, timeout=180)
        response.raise_for_status() 
        result = response.json()

        # Menangani jika model sedang loading
        if isinstance(result, dict) and result.get("error"):
            error_message = result.get("error", "")
            if "is currently loading" in error_message:
                wait_time = result.get("estimated_time", 20.0) + 5.0
                print(f"Model sedang loading. Menunggu {wait_time} detik dan mencoba lagi...")
                time.sleep(wait_time)
                response = requests.post(API_URL, headers=HEADERS, json=payload, timeout=180)
                response.raise_for_status()
                result = response.json()

        # Urutkan hasil berdasarkan skor dan ambil label dengan skor tertinggi
        best_result = sorted(result[0], key=lambda x: x['score'], reverse=True)[0]
        return best_result['label']

    except requests.exceptions.Timeout:
        return "Error: Timeout ke server AI"
    except requests.exceptions.RequestException:
        return "Error: Koneksi ke server AI gagal"
    except (KeyError, IndexError, TypeError):
        return "Error: Format respon dari API tidak dikenali"

def get_jra_details(klasifikasi_lengkap: str, jra_df: pd.DataFrame):
    """Mencari detail retensi dari DataFrame pedoman JRA."""
    if jra_df is None: 
        return "N/A", "N/A", "DataFrame Pedoman tidak dimuat"
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
    """Menampilkan halaman utama."""
    return render_template("index.html")

@app.route("/process-file/", methods=['POST'])
def process_file():
    """Menerima file, memuat pedoman, memproses, dan mengembalikan hasilnya."""
    
    if 'file' not in request.files:
        return "Error: Tidak ada file yang diunggah.", 400
    uploaded_file = request.files['file']
    if uploaded_file.filename == '':
        return "Error: Tidak ada file yang dipilih.", 400

    # Memuat Pedoman JRA hanya saat dibutuhkan
    try:
        column_names = ["Kode", "Uraian", "Retensi Aktif", "Retensi Inaktif", "Keterangan"]
        jra_details_df = pd.read_csv(
            JRA_FILE_PATH, engine='python', header=None, names=column_names
        )
        jra_details_df.set_index('Kode', inplace=True)
    except Exception as e:
        return f"Error Kritis: Gagal memuat file pedoman JRA '{JRA_FILE_PATH}'. Pastikan file ada di folder yang benar. Error: {e}", 500

    # Memproses File Unggahan Pengguna
    temp_path = f"temp_{uploaded_file.filename}"
    try:
        uploaded_file.save(temp_path)
        df_to_process = pd.read_excel(temp_path, engine='openpyxl')
        
        if 'Judul Dokumen' not in df_to_process.columns:
            raise ValueError("File Excel harus memiliki kolom bernama 'Judul Dokumen'")
            
        # Panggilan ke classify_title TIDAK LAGI memerlukan jra_labels
        df_to_process['Klasifikasi'] = df_to_process['Judul Dokumen'].apply(
            lambda title: classify_title(str(title))
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