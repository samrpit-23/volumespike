# Nifty 500 Volume Scanner

Streamlit app that lists Nifty 500 stocks whose volume is X times their average volume
(default 5x, adjustable with a slider).

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy (GitHub → Streamlit Community Cloud)

1. Create a new GitHub repo and push these files to the root:
   ```bash
   git init
   git add app.py requirements.txt README.md
   git commit -m "Nifty 500 volume scanner"
   git branch -M main
   git remote add origin https://github.com/<your-username>/nifty500-volume-scanner.git
   git push -u origin main
   ```
2. Go to https://share.streamlit.io and sign in with GitHub.
3. Click **Create app** → pick your repo, branch `main`, main file `app.py`.
4. Click **Deploy**. You get a public URL like `https://<name>.streamlit.app`.

## If the NSE list fails to load

NSE sometimes blocks cloud IPs. Download `ind_nifty500list.csv` from
https://www.niftyindices.com (Indices → Nifty 500 → constituents), rename it to
`nifty500.csv`, put it in the repo root, and push. The app falls back to it automatically.

## How the multiple is calculated

`Volume Multiple = latest day volume ÷ average volume of previous N days` (N = 20 by default).
