
import os
import io
import time
import requests
import pandas as pd
import dask.dataframe as dd
from dotenv import load_dotenv
from fastapi import FastAPI, Request, File, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

# Memuat variabel rahasia dari file .env atau sejenisnya
load_dotenv() 

# --- KONFIGURASI GLOBAL ---
HF_API_KEY = os.getenv("HF_API_KEY")
API_URL = "https://api-inference.huggingface.co/models/facebook/bart-large-mnli"
HEADERS = {"Authorization": f"Bearer {HF_API_KEY}"}

# --- BAGIAN BARU: MEMUAT PEDOMAN JRA DARI FILE SECARA OTOMATIS ---
JRA_FILE_PATH = "JRA.xlsx - Sheet1.csv"  # Pastikan nama file ini sama persis
JRA_LABELS = []
JRA_DETAILS_DF = None

try:
    # 1. Baca file CSV pedoman JRA ke dalam Pandas DataFrame
    JRA_DETAILS_DF = pd.read_csv(JRA_FILE_PATH)
    
    # 2. Buat daftar label lengkap untuk AI (contoh: "PR.01.01 Naskah Perjanjian...")
    #    Kita gabungkan kolom 'Kode' dan 'Uraian' dari file Anda
    JRA_LABELS = (JRA_DETAILS_DF['Kode'] + " " + JRA_DETAILS_DF['Uraian']).tolist()

    # 3. Siapkan DataFrame untuk pencarian detail yang cepat
    JRA_DETAILS_DF['KlasifikasiLengkap'] = JRA_LABELS
    JRA_DETAILS_DF.set_index('KlasifikasiLengkap', inplace=True)
    print("SUCCESS: Pedoman JRA berhasil dimuat dari file.")

except FileNotFoundError:
    print(f"FATAL ERROR: File pedoman '{JRA_FILE_PATH}' tidak ditemukan!")
    print("Pastikan file tersebut ada di folder yang sama dengan main.py")
    # Hentikan aplikasi jika pedoman tidak ada, atau gunakan daftar contoh
    JRA_LABELS = ["ERROR: File Pedoman JRA tidak ditemukan"]


# --- FUNGSI INTI AI ---
def classify_title(title: str):
    """Mengirim judul ke Hugging Face API untuk klasifikasi Zero-Shot."""
    if not JRA_LABELS or "ERROR" in JRA_LABELS[0]:
        return "Klasifikasi tidak bisa dilakukan, pedoman JRA tidak dimuat."

    payload = {
        "inputs": title,
        "parameters": {"candidate_labels": JRA_LABELS},
    }
    try:
        response = requests.post(API_URL, headers=HEADERS, json=payload, timeout=20)
        response.raise_for_status() 
        result = response.json()
        return result['labels'][0]
    except requests.exceptions.RequestException as e:
        print(f"Error saat menghubungi API: {e}")
        return "Error Klasifikasi API"
    except (KeyError, IndexError):
        print(f"Respon API tidak sesuai format: {response.text}")
        return "Error Format API"

# --- FUNGSI BARU: PENCARIAN DETAIL JRA ---
def get_jra_details(klasifikasi_lengkap: str):
    """Mencari detail retensi dari DataFrame pedoman JRA."""
    if JRA_DETAILS_DF is None or klasifikasi_lengkap not in JRA_DETAILS_DF.index:
        return "N/A", "N/A", "Tidak Ditemukan di Pedoman"
    
    try:
        detail = JRA_DETAILS_DF.loc[klasifikasi_lengkap]
        # Pastikan nama kolom di bawah ini sama persis dengan header di file CSV Anda
        return detail['Retensi Aktif'], detail['Retensi Inaktif'], detail['Keterangan']
    except KeyError:
        return "N/A", "N/A", "Error saat mencari detail"


# --- SETUP APLIKASI FASTAPI ---
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# --- ENDPOINTS ---
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Menampilkan halaman utama (index.html)."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/process-file/")
async def process_file(file: UploadFile = File(...)):
    """Menerima file, memprosesnya dengan Dask dan AI, dan mengembalikan hasilnya."""
    temp_path = f"temp_{file.filename}"
    try:
        with open(temp_path, "wb") as buffer:
            buffer.write(await file.read())

        df = pd.read_excel(temp_path, engine='openpyxl')
        
        if 'Judul Dokumen' not in df.columns:
            raise ValueError("File Excel harus memiliki kolom bernama 'Judul Dokumen'")
            
        ddf = dd.from_pandas(df, npartitions=4)

        def classify_partition(partition_df: pd.DataFrame) -> pd.DataFrame:
            partition_df['Klasifikasi'] = partition_df['Judul Dokumen'].apply(
                lambda title: (time.sleep(0.1), classify_title(str(title)))[1]
            )
            return partition_df

        result_ddf = ddf.map_partitions(classify_partition, meta=ddf._meta)
        result_df = result_ddf.compute()

        # Terapkan fungsi pencarian detail yang baru dan lebih canggih
        result_df[['Aktif', 'Inaktif', 'Keterangan']] = result_df['Klasifikasi'].apply(
            lambda x: pd.Series(get_jra_details(x))
        )

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            result_df.to_excel(writer, index=False, sheet_name='Hasil Klasifikasi')
        output.seek(0)

        filename = f"hasil_klasifikasi_{file.filename}"
        headers = {'Content-Disposition': f'attachment; filename="{filename}"'}
        
        return StreamingResponse(output, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers=headers)

    except ValueError as e:
        return {"error": str(e)}
    
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)