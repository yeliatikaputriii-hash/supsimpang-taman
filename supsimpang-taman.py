"""
app.py - Server Flask untuk website Sup Simpang Taman Online

Fungsi:
  1. Menampilkan website (technopreneur.html / index.html) beserta foto dan QRIS.
  2. API /api/products  -> daftar menu dan harga dari server.
  3. API /api/order     -> menerima pesanan, menghitung ulang total di server
                           (harga tidak bisa dimanipulasi dari browser), lalu
                           menyimpan ke database SQLite (orders.db).
  4. Halaman /admin     -> pemilik melihat pesanan dan menandai pembayaran
                           sudah dikonfirmasi. Dilindungi login (Basic Auth).

Cara menjalankan:
  pip install flask
  python app.py
  Buka http://127.0.0.1:5000

Ganti password admin sebelum dipakai sungguhan:
  Windows (CMD):  set ADMIN_PASSWORD=passwordkuat  lalu  python app.py
"""
import os, re, json, sqlite3
from datetime import datetime
from functools import wraps
from flask import Flask, jsonify, request, send_from_directory, Response, abort
from markupsafe import escape

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "orders.db")
HTML_FILE = "technopreneur.html"          # ganti ke "index.html" jika nama file Anda itu

WA_NUMBER = "6282126778881"               # WhatsApp usaha, format internasional tanpa +
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASSWORD", "ganti-password")
DELIVERY_FEE = None                       # None = dikonfirmasi saat pemesanan. Isi angka jika sudah ada tarif

# ---------- DATA MENU (id harus sama dengan di HTML) ----------
PRODUCTS = {
 "s1":("Sup Daging",32000),"s2":("Sup Daging + Nasi",35000),"s3":("Sup Buntut",40000),
 "s4":("Sup Buntut + Nasi",45000),"s5":("Buntut Goreng + Nasi",45000),
 "n1":("Nasi Goreng Telur SST",20000),"n2":("Nasi Goreng Ayam Geprek",25000),
 "n3":("Nasi Goreng Buntut",45000),"n4":("Nasi Goreng Daging",25000),
 "a1":("Ayam Geprek",18000),"a2":("Nasi Ayam Geprek",20000),"a3":("Indomie Ayam Geprek",25000),
 "k1":("Kentang Goreng",15000),"k2":("Perkedel",3000),
 "j1":("Jus Alpukat",15000),"j2":("Jus Mangga",15000),"j3":("Jus Tomat",15000),
 "j4":("Jus Nanas",15000),"j5":("Jus Jambu Biji",15000),"j6":("Jus Sirsak",15000),
 "j7":("Jus Buah Naga",15000),"j8":("Jus Wortel",15000),"j9":("Jus Timun",10000),
 "j10":("Fresh Jus",18000),"j11":("Jus Campur (Mix)",18000),
 "j12":("Jeruk Peras Dingin",15000),"j13":("Jeruk Peras Panas",12000),
 "m1":("Kopi Panggang",6000),"m2":("Kopi Panggang Aren",10000),"m3":("Coklat Panas",10000),
 "m4":("Coklat Dingin",12000),"m5":("Lemon Tea Panas",10000),"m6":("Lemon Tea Dingin",12000),
 "m7":("Teh Manis Panas",5000),"m8":("Teh Manis Dingin",8000),"m9":("Mineral",5000),
}
ORDER_TYPES = {"Makan di tempat", "Ambil sendiri", "Pesan antar"}
PAY_METHODS = {"QRIS", "Tunai", "Transfer bank"}

app = Flask(__name__)

# ---------- DATABASE ----------
def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created TEXT, name TEXT, phone TEXT, order_type TEXT, address TEXT,
            note TEXT, pay TEXT, items TEXT, subtotal INTEGER, total INTEGER,
            status TEXT DEFAULT 'Menunggu Konfirmasi')""")

# ---------- LOGIN ADMIN ----------
def need_login(f):
    @wraps(f)
    def w(*a, **k):
        au = request.authorization
        if not au or au.username != ADMIN_USER or au.password != ADMIN_PASS:
            return Response("Login diperlukan", 401, {"WWW-Authenticate": 'Basic realm="Admin"'})
        return f(*a, **k)
    return w

# ---------- HALAMAN WEBSITE ----------
@app.route("/")
def home():
    return send_from_directory(BASE, HTML_FILE)

@app.route("/<path:fn>")
def files(fn):
    # Hanya sajikan foto dan QRIS, bukan app.py atau orders.db
    if not re.search(r"\.(jpg|jpeg|png|webp|gif|svg|ico)$", fn, re.I):
        abort(404)
    return send_from_directory(BASE, fn)

# ---------- API ----------
@app.get("/api/products")
def api_products():
    return jsonify([{"id": i, "name": n, "price": p} for i, (n, p) in PRODUCTS.items()])

@app.post("/api/order")
def api_order():
    d = request.get_json(silent=True) or {}
    name = str(d.get("name", "")).strip()[:80]
    phone = re.sub(r"[\s-]", "", str(d.get("phone", "")))
    otype = d.get("type")
    address = str(d.get("address", "")).strip()[:300]
    note = str(d.get("note", "")).strip()[:300]
    pay = d.get("pay")

    errors = []
    if not name: errors.append("Nama wajib diisi")
    if not re.fullmatch(r"(\+?62|0)8[0-9]{7,12}", phone): errors.append("Nomor WhatsApp tidak valid")
    if otype not in ORDER_TYPES: errors.append("Jenis pesanan tidak valid")
    if otype == "Pesan antar" and not address: errors.append("Alamat wajib untuk pesan antar")
    if pay not in PAY_METHODS: errors.append("Metode pembayaran tidak valid")

    # Hitung ulang dari harga server, abaikan harga dari browser
    lines, subtotal = [], 0
    for it in d.get("items", []):
        pid, qty = it.get("id"), it.get("qty")
        if pid not in PRODUCTS or not isinstance(qty, int) or not 1 <= qty <= 99:
            errors.append("Item pesanan tidak valid"); break
        pname, price = PRODUCTS[pid]
        lines.append({"id": pid, "name": pname, "qty": qty, "price": price, "sum": price * qty})
        subtotal += price * qty
    if not lines: errors.append("Keranjang kosong")
    if errors:
        return jsonify(ok=False, errors=errors), 400

    fee = DELIVERY_FEE if (otype == "Pesan antar" and DELIVERY_FEE is not None) else 0
    total = subtotal + fee
    with db() as con:
        cur = con.execute(
            "INSERT INTO orders(created,name,phone,order_type,address,note,pay,items,subtotal,total) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), name, phone, otype, address, note, pay,
             json.dumps(lines, ensure_ascii=False), subtotal, total))
        oid = cur.lastrowid
    return jsonify(ok=True, order_id=oid, subtotal=subtotal, total=total,
                   status="Menunggu Konfirmasi", wa_number=WA_NUMBER)

# ---------- ADMIN ----------
@app.route("/admin")
@need_login
def admin():
    rows = db().execute("SELECT * FROM orders ORDER BY id DESC LIMIT 200").fetchall()
    out = []
    for r in rows:
        items = "<br>".join(f"{escape(i['name'])} x {i['qty']} = Rp{i['sum']:,}".replace(",", ".") for i in json.loads(r["items"]))
        btn = "" if r["status"] == "Dikonfirmasi" else f'<form method="post" action="/admin/confirm/{r["id"]}"><button>Konfirmasi</button></form>'
        out.append(f"<tr><td>#{r['id']}<br><small>{r['created']}</small></td>"
                   f"<td>{escape(r['name'])}<br>{escape(r['phone'])}</td>"
                   f"<td>{escape(r['order_type'])}<br><small>{escape(r['address'])}</small></td>"
                   f"<td>{items}<br><small>{escape(r['note'])}</small></td>"
                   f"<td>{escape(r['pay'])}</td><td><b>Rp{r['total']:,}</b></td>".replace(",", ".") +
                   f"<td>{escape(r['status'])}{btn}</td></tr>")
    return f"""<!DOCTYPE html><meta charset=utf-8><title>Admin</title>
<style>body{{font-family:sans-serif;padding:16px}}table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ddd;padding:8px;vertical-align:top;font-size:14px}}th{{background:#3e2418;color:#fff}}</style>
<h2>Pesanan Sup Simpang Taman</h2>
<table><tr><th>No</th><th>Pelanggan</th><th>Jenis</th><th>Pesanan</th><th>Bayar</th><th>Total</th><th>Status</th></tr>
{''.join(out) or '<tr><td colspan=7>Belum ada pesanan</td></tr>'}</table>"""

@app.post("/admin/confirm/<int:oid>")
@need_login
def confirm(oid):
    with db() as con:
        con.execute("UPDATE orders SET status='Dikonfirmasi' WHERE id=?", (oid,))
    return Response(status=303, headers={"Location": "/admin"})

if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=5000, debug=True)
