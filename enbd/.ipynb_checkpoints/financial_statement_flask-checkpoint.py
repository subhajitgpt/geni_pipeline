from flask import Flask, request, render_template_string
import fitz  # PyMuPDF
import tempfile
import re
import os

app = Flask(__name__)

# -------- Helpers --------
def to_float(s):
    try:
        return float(s.replace(",", ""))
    except Exception:
        return None

def safe_div(a, b):
    try:
        return round(a / b, 4) if a is not None and b not in (None, 0) else None
    except Exception:
        return None

def fmt_pct(x):
    return f"{x*100:.2f}%" if x is not None else "N/A"

# -------- Patterns (capture current & prior period when available) --------
patterns_dual = {
    "Interest and Similar Income": r"Interest and similar income\s+([\d,]+)\s+([\d,]+)",
    "Interest and Similar Expense": r"Interest and similar expense\s+\(([\d,]+)\)\s+\(([\d,]+)\)",
    "Net Interest Income": r"Net interest income\s+([\d,]+)\s+([\d,]+)",
    "Islamic Financing Income": r"Income from Islamic financing and investment products\s+([\d,]+)\s+([\d,]+)",
    "Distribution on Islamic Deposits": r"Distribution on Islamic deposits and profit paid to Sukuk holders\s+\(([\d,]+)\)\s+\(([\d,]+)\)",
    "Net Income from Islamic": r"Net income from Islamic financing and investment products\s+([\d,]+)\s+([\d,]+)",
    "Net Fees and Commission": r"Net fee and commission income\s+([\d,]+)\s+([\d,]+)",
    "Net Gain on Trading Securities": r"Net gain on trading securities\s+([\d,]+)\s+([\d,]+)",
    "Other Operating Income": r"Other operating income.*?\s+([\d,]+)\s+([\d,]+)",
    "Total Operating Income": r"Total operating income\s+([\d,]+)\s+([\d,]+)",
    "General and Administrative Expenses": r"General and administrative expenses\s+\(([\d,]+)\)\s+\(([\d,]+)\)",
    "Operating Profit Before Impairment": r"Operating profit before impairment\s+([\d,]+)\s+([\d,]+)",
    "Net Impairment Reversal": r"Net impairment (?:reversal|loss)\s+([\-\d,]+)\s+([\-\d,]+)",
    "Profit Before Tax": r"Profit for the period before taxation\s+([\d,]+)\s+([\d,]+)",
    "Taxation Charge": r"Taxation charge\s+\(([\d,]+)\)\s+\(([\d,]+)\)",
    "Profit for the Period": r"Profit for the period\s+([\d,]+)\s+([\d,]+)",
    "Earnings Per Share (AED)": r"Earnings per share\s*\(AED\)\s+([\d\.]+)\s+([\d\.]+)",
}

patterns_single = {
    "Gross Loans and Receivables": r"Gross loans and receivables\s+([\d,]+)\s+[\d,]+",
    "Expected Credit Losses (Loans)": r"Less:\s*Expected credit losses\s+\(([\d,]+)\)\s+\([\d,]+\)",
    "Net Loans and Receivables": r"Net loans and receivables\s+([\d,]+)\s+[\d,]+",
    "Credit-Impaired Loans (NPLs)": r"Total of credit impaired loans and receivables\s+([\d,]+)\s+[\d,]+",
    "Total Assets": r"Segment Assets[\s\S]*?(\d{1,3}(?:,\d{3})+)\s*\n\s*Segment Liabilities",
    "Fee and Commission Income": r"Fee and commission income\s+([\d,]+)\s+[\d,]+",
    "Fee and Commission Expense": r"Fee and commission expense\s+\(([\d,]+)\)\s+\([\d,]+\)",
    "FX & Derivative Income": r"Foreign exchange and derivative income.*?\s+([\d,]+)\s+[\d,]+",
}

def extract_dual(text):
    out = {}
    for label, pat in patterns_dual.items():
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            curr = to_float(m.group(1))
            prior = to_float(m.group(2)) if m.lastindex and m.lastindex >= 2 else None
            out[label] = {"current": curr, "prior": prior}
        else:
            out[label] = {"current": None, "prior": None}
    return out

def extract_single(text):
    out = {}
    for label, pat in patterns_single.items():
        m = re.search(pat, text, re.IGNORECASE)
        out[label] = to_float(m.group(1)) if m else None
    return out

def parse_pdf(file_path):
    with fitz.open(file_path) as doc:
        full_text = "\n".join(page.get_text() for page in doc)
    dual = extract_dual(full_text)
    single = extract_single(full_text)
    return dual, single

# Jinja filter for percentages
@app.template_filter("to_pct")
def to_pct(value):
    return fmt_pct(value)

@app.route("/")
def index():
    return '''
    <html>
    <head><title>Emirates NBD Q1 Analyzer</title></head>
    <body style="font-family: Arial; padding: 40px;">
        <h2>📄 Upload Emirates NBD Q1 2025 Financial Statement (PDF)</h2>
        <form method="post" action="/upload" enctype="multipart/form-data">
            <input type="file" name="pdf_file" required>
            <input type="submit" value="Analyze">
        </form>
    </body>
    </html>
    '''

@app.route("/upload", methods=["POST"])
def upload():
    if "pdf_file" not in request.files:
        return "Missing file", 400
    f = request.files["pdf_file"]
    if f.filename == "":
        return "Empty filename", 400

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    try:
        f.save(tmp.name)
        path = tmp.name

        dual, single = parse_pdf(path)

        def cur(k): return (dual.get(k) or {}).get("current")
        def prv(k): return (dual.get(k) or {}).get("prior")

        toi_c = cur("Total Operating Income")
        toi_p = prv("Total Operating Income")
        ga_c  = cur("General and Administrative Expenses")
        opb_c = cur("Operating Profit Before Impairment")
        pbt_c = cur("Profit Before Tax")
        tax_c = cur("Taxation Charge")
        pat_c = cur("Profit for the Period")
        eps_c = cur("Earnings Per Share (AED)")
        eps_p = prv("Earnings Per Share (AED)")

        nfee_c = cur("Net Fees and Commission")
        trading_c = cur("Net Gain on Trading Securities")
        other_c = cur("Other Operating Income")
        fx_c = single.get("FX & Derivative Income")

        gross_loans = single.get("Gross Loans and Receivables")
        ecl_loans   = single.get("Expected Credit Losses (Loans)")
        net_loans   = single.get("Net Loans and Receivables")
        npls        = single.get("Credit-Impaired Loans (NPLs)")

        total_assets = single.get("Total Assets")

        # -------- Ratios (bank-meaningful) --------
        ratios = []

        # Profitability & efficiency
        ratios.append({
            "name": "Cost-to-Income",
            "formula": "G&A Expenses / Total Operating Income",
            "calc": f"{ga_c} / {toi_c}",
            "value": safe_div(ga_c, toi_c)
        })
        ratios.append({
            "name": "Net Profit Margin",
            "formula": "Profit for the Period / Total Operating Income",
            "calc": f"{pat_c} / {toi_c}",
            "value": safe_div(pat_c, toi_c)
        })
        ratios.append({
            "name": "Pre-Impairment Operating Margin",
            "formula": "Operating Profit Before Impairment / Total Operating Income",
            "calc": f"{opb_c} / {toi_c}",
            "value": safe_div(opb_c, toi_c)
        })

        # Income mix
        ratios.append({
            "name": "Fee Income Mix",
            "formula": "Net Fee & Commission / Total Operating Income",
            "calc": f"{nfee_c} / {toi_c}",
            "value": safe_div(nfee_c, toi_c)
        })
        mix_numer = fx_c if fx_c is not None else ((trading_c or 0) + (other_c or 0))
        ratios.append({
            "name": "Markets & Other Income Mix",
            "formula": "(FX & Derivatives OR Trading + Other) / Total Operating Income",
            "calc": f"{mix_numer} / {toi_c}",
            "value": safe_div(mix_numer, toi_c)
        })

        # Credit quality
        ratios.append({
            "name": "NPL Ratio",
            "formula": "Credit-Impaired Loans / Gross Loans",
            "calc": f"{npls} / {gross_loans}",
            "value": safe_div(npls, gross_loans)
        })
        ratios.append({
            "name": "Coverage Ratio",
            "formula": "Loan Loss Provisions (ECL) / NPLs",
            "calc": f"{ecl_loans} / {npls}",
            "value": safe_div(ecl_loans, npls)
        })
        ratios.append({
            "name": "ECL / Gross Loans",
            "formula": "Total ECL (Loans) / Gross Loans",
            "calc": f"{ecl_loans} / {gross_loans}",
            "value": safe_div(ecl_loans, gross_loans)
        })

        # Tax efficiency
        ratios.append({
            "name": "Effective Tax Rate",
            "formula": "Taxation Charge / Profit Before Tax",
            "calc": f"{tax_c} / {pbt_c}",
            "value": safe_div(tax_c, pbt_c)
        })

        # Scale profitability (approx since we only have period-end assets)
        ratios.append({
            "name": "ROA (Quarter, Approx.)",
            "formula": "Profit for the Period / Total Assets",
            "calc": f"{pat_c} / {total_assets}",
            "value": safe_div(pat_c, total_assets)
        })

        # EPS trend
        eps_yoy = safe_div((eps_c - eps_p) if (eps_c is not None and eps_p is not None) else None, eps_p)
        ratios.append({
            "name": "EPS YoY Change",
            "formula": "(EPS 2025 - EPS 2024) / EPS 2024",
            "calc": f"{eps_c} - {eps_p} over {eps_p}",
            "value": eps_yoy
        })

        # Recommendations (very light-touch)
        recommendations = []
        ci = next((r for r in ratios if r["name"]=="Cost-to-Income"), None)
        if ci and ci["value"] is not None:
            if ci["value"] > 0.50:
                recommendations.append("🔴 Cost-to-Income > 50% this quarter; investigate operating expense levers.")
            elif ci["value"] < 0.35:
                recommendations.append("🟢 Strong cost efficiency indicated by a low Cost-to-Income ratio.")

        npl = next((r for r in ratios if r["name"]=="NPL Ratio"), None)
        cov = next((r for r in ratios if r["name"]=="Coverage Ratio"), None)
        if npl and npl["value"] is not None and npl["value"] > 0.06:
            recommendations.append("🟠 NPL ratio > 6%; review sectoral concentrations and staging migrations.")
        if cov and cov["value"] is not None and cov["value"] < 1.0:
            recommendations.append("🟠 Coverage < 100%; assess collateral, cures and write-off policy.")

        if not recommendations:
            recommendations.append("🟢 Metrics look balanced across profitability, efficiency and asset quality.")

        metrics_table = []
        for k, v in dual.items():
            metrics_table.append((k, v.get("current"), v.get("prior")))
        for k in ["Gross Loans and Receivables","Expected Credit Losses (Loans)","Net Loans and Receivables",
                  "Credit-Impaired Loans (NPLs)","Total Assets","Fee and Commission Income",
                  "Fee and Commission Expense","FX & Derivative Income"]:
            metrics_table.append((k, single.get(k), None))

        return render_template_string("""
        <html>
        <head>
            <title>ENBD Q1 2025 Report</title>
            <style>
                body { font-family: Arial; background:#f9f9f9; padding:40px; }
                .box { background:white; padding:30px; max-width:1000px; margin:auto; border-radius:12px; box-shadow:0 0 10px #ccc; }
                h2 { color:#004080; }
                table { width:100%; border-collapse:collapse; margin-top:16px; }
                th, td { padding:10px 12px; border-bottom:1px solid #eee; text-align:left; vertical-align:top; }
                th { background:#f0f4fa; }
                code { background:#eef; padding:2px 4px; border-radius:4px; }
                .muted { color:#666; font-size:12px; }
            </style>
        </head>
        <body>
            <div class="box">
                <h2>📊 Emirates NBD – Q1 2025 Financial Highlights</h2>
                <div class="muted">Figures parsed from the uploaded Q1-2025 interim financial statements PDF.</div>

                <h3>Extracted Metrics (Current vs Prior)</h3>
                <table>
                    <tr><th>Metric</th><th>Q1-2025</th><th>Q1-2024</th></tr>
                    {% for k, curv, prv in metrics %}
                      <tr>
                        <td>{{k}}</td>
                        <td>{{ '{:,.2f}'.format(curv) if curv is not none else 'Not Found' }}</td>
                        <td>{{ '{:,.2f}'.format(prv) if prv is not none else '—' }}</td>
                      </tr>
                    {% endfor %}
                </table>

                <h3>Key Ratios with Formulas</h3>
                <table>
                    <tr><th>Ratio</th><th>Formula</th><th>Calculation</th><th>Value</th></tr>
                    {% for r in ratios %}
                      <tr>
                        <td>{{ r.name }}</td>
                        <td><code>{{ r.formula }}</code></td>
                        <td><code>{{ r.calc }}</code></td>
                        <td>{{ r.value|to_pct }}</td>
                      </tr>
                    {% endfor %}
                </table>

                <h3>🧠 Recommendations</h3>
                <ul>
                    {% for rec in recommendations %}
                      <li>{{ rec }}</li>
                    {% endfor %}
                </ul>
            </div>
        </body>
        </html>
        """, metrics=metrics_table, ratios=ratios, recommendations=recommendations)
    except Exception as e:
        return f"Error: {str(e)}", 500
    finally:
        tmp.close()
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)

if __name__ == "__main__":
    app.run(debug=True)  # Set debug=False for production