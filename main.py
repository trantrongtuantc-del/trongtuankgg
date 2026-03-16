# Vào trong thư mục crypto-scanner (nơi có main.py)
cd crypto-scanner

# Init git ở đây, KHÔNG phải ở ngoài
git init
git add .
git commit -m "fix: move files to root"

# Nếu repo GitHub đã tạo rồi thì force push
git remote add origin https://github.com/TÊN_BẠN/crypto-scanner.git
git push -u origin main --force
```

**Kiểm tra cấu trúc đúng** — root repo phải trông như này:
```
/ (root)
├── main.py          ← phải ở đây
├── indicators.py
├── scanner.py
├── db.py
├── notifier.py
├── requirements.txt
├── railway.toml
└── README.md
```

**Sai** (đang bị như này):
```
/ (root)
└── crypto-scanner/
    ├── main.py      ← Railway không thấy
    └── ...
