# main.py
import os
# Impor komponen-komponen baru di bawah ini
from fastapi import FastAPI, Request, File, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates # <-- Tambahkan ini
from dotenv import load_dotenv
# main.py
import dask.dataframe as dd
import pandas as pd
import io
import time
# ... import lainnya yang sudah ada

app = FastAPI()

# Mounting folder static
app.mount("/static", StaticFiles(directory="static"), name="static") # <-- Tambahkan ini

# Konfigurasi folder template untuk file HTML
templates = Jinja2Templates(directory="templates")

# Endpoint untuk Halaman Utama (GET)
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
	"""Menampilkan halaman utama (index.html)."""
	return templates.TemplateResponse("index.html", {"request": request})

@app.post("/process-file/")
async def process_file(file: UploadFile = File(...)):
	"""
	Menerima file, memprosesnya dengan Dask dan AI, 
	dan mengembalikan hasilnya sebagai file Excel baru.
	"""
	
	# 1. Simpan file yang diunggah sementara untuk dibaca
	temp_path = f"temp_{file.filename}"
	try:
		# ---- SEMUA KODE YANG SUDAH ANDA TULIS ADA DI SINI ----
		# ---- DARI 'with open' HINGGA MEMBUAT FILE OUTPUT ----
		
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

		def get_jra_details(klasifikasi):
			if klasifikasi == "REN.01.01 Laporan Bulanan":
				return "1 Tahun Setelah Tahun Anggaran Berakhir", "1 Tahun", "Musnah"
			elif klasifikasi == "KEU.02.01 Laporan Keuangan":
				return "5 Tahun", "Permanen", "Disimpan Permanen"
			else:
				return "N/A", "N/A", "Perlu Tinjauan"

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

	# ----- BAGIAN YANG HILANG DIMULAI DARI SINI -----

	except ValueError as e: # Rencana "JIKA GAGAL" karena kolom salah
		# Menangani error jika kolom tidak ditemukan
		return {"error": str(e)}
	
	finally: # Rencana "APAPUN YANG TERJADI"
		# Pastikan file sementara selalu dihapus, bahkan jika terjadi error
		if os.path.exists(temp_path):
			os.remove(temp_path)
			
