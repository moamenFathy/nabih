# 🎙️ Google Colab XTTS-v2 Voice Cloning Server for Nabih

This directory contains the ready-to-run Google Colab Notebook to host **Coqui XTTS-v2** on a free Nvidia T4 GPU.

---

## 🚀 How to Run in 3 Easy Steps:

### Step 1: Open Notebook in Google Colab
1. Go to [Google Colab](https://colab.research.google.com).
2. Click **Upload** and upload `colab/nabih_xtts_server.ipynb`.
3. Go to **Runtime -> Change runtime type** and ensure **T4 GPU** is selected.

---

### Step 2: (Optional) Upload Your Voice Sample for Cloning
- In Google Colab, click the **Folder icon 📁** on the left sidebar.
- Upload a clean 6-second `.wav` audio recording and name it **`my_voice.wav`**.
  *(If you don't upload a file, the notebook automatically creates a clean default Egyptian voice sample).*

---

### Step 3: Run the Notebook & Copy the Tunnel URL
1. Click **Runtime -> Run all** (takes ~1 minute to download the model).
2. At the bottom of the final cell, you will see a public Cloudflare URL:
   ```text
   =================================================================
   🎉 YOUR NABIH XTTS ENDPOINT IS READY:
   👉 https://xxxx-xxxx-xxxx.trycloudflare.com
   =================================================================
   ```
3. Copy that URL into your local Nabih `.env` file:
   ```env
   TTS_PROVIDER=xtts
   XTTS_API_URL=https://xxxx-xxxx-xxxx.trycloudflare.com
   ```
4. Run Nabih locally on your desktop:
   ```powershell
   .\.venv\Scripts\python.exe main.py
   ```

---

## 🛡️ Circuit Breaker Protection:
If Google Colab disconnects or goes to sleep, Nabih's automatic **Circuit Breaker** instantly falls back to Edge-TTS (`ar-EG-ShakirNeural` / `ar-EG-SalmaNeural`) so your assistant never stops responding!
