# HNG Stage 1 – FastAPI Deployment

## 📌 Overview

This project is a minimal API built with **FastAPI** and deployed on a Linux VPS using **Nginx as a reverse proxy**.

It demonstrates:

* Basic API design
* Reverse proxy setup with Nginx
* Process management using systemd
* Secure HTTPS deployment

---

## 🚀 Live URL

👉 https://godand.duckdns.org

---

## ⚙️ Tech Stack

* Python (FastAPI)
* Uvicorn (ASGI server)
* Nginx (reverse proxy)
* systemd (process manager)
* Ubuntu Linux

---

## 🧪 API Endpoints

### 1. GET `/`

Returns a simple status message.

**Response (200):**

```json
{
  "message": "API is running"
}
```

---

### 2. GET `/health`

Health check endpoint.

**Response (200):**

```json
{
  "message": "healthy"
}
```

---

### 3. GET `/me`

Returns personal information.

**Response (200):**

```json
{
  "name": "Your Full Name",
  "email": "you@example.com",
  "github": "https://github.com/yourusername"
}
```

---

## 📦 Running Locally

### 1. Clone repo

```bash
git clone https://github.com/godhanded/HNG14.git
cd HNG14/Stage1/Devops
```

### 2. Create virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Start server

```bash
uvicorn main:app --port 8001 --reload
```

App will be available at:

```
http://127.0.0.1:8001
```

---

## 🌐 Deployment Details

* App runs on: `127.0.0.1:8001`
* Public traffic handled by **Nginx**
* HTTPS enabled using Let’s Encrypt
* HTTP traffic redirects to HTTPS (301)

### Architecture

```
Client → Nginx (443) → FastAPI (127.0.0.1:8001)
```

---

## 🔒 Key Notes

* All endpoints return:

  * `Content-Type: application/json`
  * HTTP status `200`
* API is not publicly exposed on its internal port
* Service is managed with systemd and auto-restarts on failure
* Response time is under 500ms

---

## 📁 Project Structure

```
Devops/
├── main.py
├── requirements.txt
└── README.md
```
