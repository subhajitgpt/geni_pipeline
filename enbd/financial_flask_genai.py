# app_financials.py
from flask import Flask, request, render_template_string
import fitz, tempfile, re, os, sys, json
from dotenv import load_dotenv
from openai import OpenAI

# Load API key
load_dotenv("C:\\EUacademy\\.env")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

app = Flask(__name__)

# --- helpers ---
def to_float(s):
    try: return float(s.replace(",", ""))
    except: return None

def safe_div(a, b):
    return round(a / b, 4) if a is not None and b not in (None,0) else None

def fmt_pct(x): return f"{x*100:.2f}%" if x is not None else "N/A"

patterns_dual = {
    "Total Operating Income": r"Total operating income\s+([\d,]+)\s+([\d,]+)",
    "General and Administrative Expenses": r"General and administrative expenses\s+\(([\d,]+)\)\s+\(([\d,]+)\)",
    "Operating Profit Before Impairment": r"Operating profit before impairment\s+([\d,]+)\s+([\d,]+)",
    "Profit Before Tax": r"Profit for the period before taxation\s+([\d,]+)\s+([\d,]+)",
    "Taxation Charge": r"Taxation charge\s+\(([\d,]+)\)\s+\(([\d,]+)\)",
    "Profit for the Period": r"Profit for the period\s+([\d,]+)\s+([\d,]+)",
    "Earnings Per Share (AED)": r"Earnings per share\s*\(AED\)\s+([\d\.]+)\s+([\d\.]+)",
}
patterns_single = {
    "Gross Loans": r"Gross loans and receivables\s+([\d,]+)\s+[\d,]+",
    "ECL": r"Less:\s*Expected credit losses\s+\(([\d,]+)\)\s+\([\d,]+\)",
    "NPLs": r"Total of credit impaired loans and receivables\s+([\d,]+)\s+[\d,]+",
    "Total Assets": r"Segment Assets[\s\S]*?(\d{1,3}(?:,\d{3})+)\s*\n\s*Segment Liabilities",
}

def extract_dual(text):
    out={}
    for k,p in patterns_dual.items():
        m=re.search(p,text,re.I)
        out[k]={"current":to_float(m.group(1)) if m else None,
                "prior":to_float(m.group(2)) if m and m.lastindex>=2 else None}
    return out

def extract_single(text):
    out={}
    for k,p in patterns_single.items():
        m=re.search(p,text,re.I)
        out[k]=to_float(m.group(1)) if m else None
    return out

def parse_pdf(path):
    with fitz.open(path) as doc:
        txt="\n".join(pg.get_text() for pg in doc)
    return extract_dual(txt), extract_single(txt)

def compute_ratios(dual, single):
    toi=dual["Total Operating Income"]["current"]
    ga=dual["General and Administrative Expenses"]["current"]
    opb=dual["Operating Profit Before Impairment"]["current"]
    pat=dual["Profit for the Period"]["current"]
    pbt=dual["Profit Before Tax"]["current"]
    tax=dual["Taxation Charge"]["current"]
    eps_c=dual["Earnings Per Share (AED)"]["current"]
    eps_p=dual["Earnings Per Share (AED)"]["prior"]

    gross=single["Gross Loans"]; ecl=single["ECL"]; npl=single["NPLs"]; assets=single["Total Assets"]

    ratios=[
        ("Cost-to-Income",        safe_div(ga,toi)),
        ("Net Profit Margin",     safe_div(pat,toi)),
        ("Pre-impairment Margin", safe_div(opb,toi)),
        ("NPL Ratio",             safe_div(npl,gross)),
        ("Coverage Ratio",        safe_div(ecl,npl)),
        ("ECL/Gross Loans",       safe_div(ecl,gross)),
        ("Tax Rate",              safe_div(tax,pbt)),
        ("ROA",                   safe_div(pat,assets)),
        ("EPS YoY",               safe_div((eps_c-eps_p) if eps_c and eps_p else None, eps_p)),
    ]
    return ratios

def metrics_to_context(dual, single, ratios):
    # Compact string for LLM context
    lines = ["Key metrics & ratios:"]
    for k,v in dual.items():
        lines.append(f"{k}: current={v['current']}, prior={v['prior']}")
    for k,v in single.items():
        lines.append(f"{k}: {v}")
    lines.append("Ratios:")
    for name,val in ratios:
        lines.append(f"{name}: {fmt_pct(val)}")
    return "\n".join(lines)

# --- Jinja filter
@app.template_filter("pct")
def pct(v): return fmt_pct(v)

# --------- Flask route (upload + one-off prompt) ----------
@app.route("/", methods=["GET","POST"])
def index():
    dual=single=ratios=recs=None
    answer=None
    if request.method=="POST" and "pdf_file" in request.files:
        f=request.files["pdf_file"]
        if f.filename:
            tmp=tempfile.NamedTemporaryFile(delete=False,suffix=".pdf")
            f.save(tmp.name)
            dual,single=parse_pdf(tmp.name)
            os.unlink(tmp.name)

            ratios = compute_ratios(dual, single)
            recs=[]
            # light heuristics
            ci = dict(ratios).get("Cost-to-Income")
            npl = dict(ratios).get("NPL Ratio")
            if ci is not None and ci>0.50: recs.append("High cost-to-income; review operating expenses.")
            if npl is not None and npl>0.06: recs.append("NPL ratio elevated; examine credit concentrations.")

            # Optional OpenAI one-off
            prompt=request.form.get("prompt","").strip()
            if prompt and client:
                context = metrics_to_context(dual, single, ratios)
                try:
                    resp=client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role":"system","content":"You are a bank financial analyst. Be concise and numeric."},
                            {"role":"user","content":f"{context}\n\nUser prompt: {prompt}"}
                        ],
                        temperature=0.2
                    )
                    answer=resp.choices[0].message.content
                except Exception as e:
                    answer=f"[OpenAI error] {e}"

    return render_template_string("""
    <h2>Upload ENBD Q1 PDF</h2>
    <form method=post enctype=multipart/form-data>
      <input type=file name=pdf_file required>
      <br><textarea name=prompt placeholder="Optional: ask a question for OpenAI"></textarea>
      <br><input type=submit value=Analyze>
    </form>
    {% if ratios %}
      <h3>Ratios</h3>
      <ul>
        {% for name,val in ratios %}
          <li>{{name}}: {{val|pct}}</li>
        {% endfor %}
      </ul>
      {% if recs %}
        <h3>Recommendations</h3>
        <ul>{% for r in recs %}<li>{{r}}</li>{% endfor %}</ul>
      {% endif %}
    {% endif %}
    {% if answer %}<h3>OpenAI Answer</h3><div>{{answer}}</div>{% endif %}
    """, ratios=ratios, recs=recs, answer=answer)

# --------- CLI chat mode (loop until 'q') ----------
def cli_chat():
    if not client:
        print("OPENAI_API_KEY not configured in C:\\EUacademy\\.env")
        return

    # Optional: parse a PDF to seed context
    context = ""
    try:
        pdf_path = input("PDF path for context (Enter to skip): ").strip()
        if pdf_path:
            dual, single = parse_pdf(pdf_path)
            ratios = compute_ratios(dual, single)
            context = metrics_to_context(dual, single, ratios)
            print("Parsed PDF. Context prepared.")
        else:
            print("No PDF context. Chatting without financial context.")
    except Exception as e:
        print(f"[PDF parse skipped] {e}")

    print("\n💬 Chat mode (type 'q' to quit)")
    while True:
        q = input("\nYour prompt> ").strip()
        if q.lower() == "q":
            print("Bye!")
            break
        if not q:
            continue
        try:
            msg = (f"{context}\n\nUser prompt: {q}") if context else q
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role":"system","content":"You are a bank financial analyst. Be concise and numeric."},
                    {"role":"user","content": msg}
                ],
                temperature=0.2
            )
            print("\nAssistant:", resp.choices[0].message.content.strip())
        except Exception as e:
            print(f"[OpenAI error] {e}")

if __name__=="__main__":
    # Run CLI loop if '--cli' is provided; otherwise run Flask
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        cli_chat()
    else:
        app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False)
