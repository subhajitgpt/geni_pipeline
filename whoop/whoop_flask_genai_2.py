# app_whoop_session.py
from flask import Flask, render_template_string, request, url_for, session
import pandas as pd
import os
import matplotlib.pyplot as plt
import io
import base64
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from openai import OpenAI

# --- Config & OpenAI ---
load_dotenv("C:\\EUacademy\\.env")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ⚠️ change this in production
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-change-me")

HTML_FORM = """
<!doctype html>
<title>Health & Sleep Data Analyzer</title>
<style>
body { font-family: Arial, sans-serif; margin: 40px; }
h2, h3, h4 { color: #2c3e50; }
table { border-collapse: collapse; margin-bottom: 20px; }
th, td { border: 1px solid #bbb; padding: 6px 12px; }
th { background: #f4f4f4; }
.summary-box { background: #eaf6fb; padding: 16px; border-radius: 8px; margin-bottom: 24px; }
img { margin-bottom: 30px; border: 1px solid #ccc; border-radius: 6px; }
.ok { background: #eef8f0; border-left: 4px solid #39a85b; padding: 10px 12px; margin: 12px 0; }
.err { background: #fdecec; border-left: 4px solid #d9534f; padding: 10px 12px; margin: 12px 0; }
textarea { width: 100%; min-height: 120px; padding: 10px; border: 1px solid #ddd; border-radius: 8px; }
button { background: #0b4f8a; color:#fff; padding:8px 14px; border:none; border-radius:8px; cursor:pointer; }
</style>

<h2>Upload your physiological_cycles_today.csv</h2>
<form method=post enctype=multipart/form-data>
  <input type=file name=file accept=".csv" required>
  <input type=submit value=Upload>
</form>
{% if error %}<p class="err">{{ error }}</p>{% endif %}
"""

HTML_RESULT = """
<!doctype html>
<title>Results</title>
<style>
body { font-family: Arial, sans-serif; margin: 40px; }
h2, h3, h4 { color: #2c3e50; }
table { border-collapse: collapse; margin-bottom: 20px; }
th, td { border: 1px solid #bbb; padding: 6px 12px; }
th { background: #f4f4f4; }
.summary-box { background: #eaf6fb; padding: 16px; border-radius: 8px; margin-bottom: 24px; }
img { margin-bottom: 30px; border: 1px solid #ccc; border-radius: 6px; }
.ok { background: #eef8f0; border-left: 4px solid #39a85b; padding: 10px 12px; margin: 12px 0; }
.err { background: #fdecec; border-left: 4px solid #d9534f; padding: 10px 12px; margin: 12px 0; }
textarea { width: 100%; min-height: 120px; padding: 10px; border: 1px solid #ddd; border-radius: 8px; }
button { background: #0b4f8a; color:#fff; padding:8px 14px; border:none; border-radius:8px; cursor:pointer; }
</style>

<h2>Quick Summary</h2>
<div class="summary-box">
  <ul>
    <li><b>Average Recovery Score:</b> {{ summary_stats['Recovery_score_']['mean'] }}</li>
    <li><b>Average Resting Heart Rate:</b> {{ summary_stats['Resting_heart_rate_(bpm)']['mean'] }} bpm</li>
    <li><b>Average HRV:</b> {{ summary_stats['Heart_rate_variability_(ms)']['mean'] }} ms</li>
    <li><b>Average Sleep Performance:</b> {{ summary_stats['Sleep_performance_']['mean'] }}</li>
    <li><b>Average Sleep Debt:</b> {{ avg_sleep_debt }} min</li>
    <li><b>Low Recovery Days (&lt;50):</b> {{ low_recovery_count }}</li>
    <li><b>High Sleep Debt Days (&gt;100 min):</b> {{ high_sleep_debt_count }}</li>
  </ul>
</div>

<h3>Overall Metrics (Bar Chart)</h3>
<img src="data:image/png;base64,{{ bar_chart }}" alt="Average Metrics">

<h3>Low Recovery Days Proportion</h3>
<img src="data:image/png;base64,{{ pie_low_recovery }}" alt="Low Recovery Pie">

<h3>High Sleep Debt Days Proportion</h3>
<img src="data:image/png;base64,{{ pie_high_sleep_debt }}" alt="High Sleep Debt Pie">

<h3>Recovery Score Distribution</h3>
<table>
  <tr><th>Category</th><th>Days</th></tr>
  <tr><td>Low (&lt;50)</td><td>{{ recovery_dist['Low'] }}</td></tr>
  <tr><td>Medium (50-79)</td><td>{{ recovery_dist['Medium'] }}</td></tr>
  <tr><td>High (&ge;80)</td><td>{{ recovery_dist['High'] }}</td></tr>
</table>

<h3>Sleep Debt Distribution</h3>
<table>
  <tr><th>Category</th><th>Days</th></tr>
  <tr><td>Low (&lt;30 min)</td><td>{{ sleep_debt_dist['Low'] }}</td></tr>
  <tr><td>Moderate (30-100 min)</td><td>{{ sleep_debt_dist['Moderate'] }}</td></tr>
  <tr><td>High (&ge;100 min)</td><td>{{ sleep_debt_dist['High'] }}</td></tr>
</table>

<h3>Highlights</h3>
<h4>Top 3 Best Recovery Days</h4>
{{ best_recovery_html|safe }}

<h4>Top 3 Worst Recovery Days</h4>
{{ worst_recovery_html|safe }}

<h4>Top 3 Highest Sleep Debt Days</h4>
{{ highest_sleep_debt_html|safe }}

<h4>Top 3 Lowest Sleep Debt Days</h4>
{{ lowest_sleep_debt_html|safe }}

<h3>Ask OpenAI about your data (optional)</h3>
<form method="post">
  <textarea name="prompt" placeholder="E.g., Suggest a 7-day plan to improve HRV given my averages and bad days.">{{ prompt or '' }}</textarea>
  <br><button type="submit">Ask</button>
</form>

{% if answer %}
<div class="ok"><b>Assistant:</b><br>
<pre style="white-space: pre-wrap; font-family: inherit;">{{ answer }}</pre>
</div>
{% endif %}

<br>
<a href="{{ url_for('upload_file') }}">Analyze another file</a>
"""

def plot_to_base64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches='tight')
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode('utf-8')
    plt.close(fig)
    return img_base64

def make_bar_chart(averages):
    fig, ax = plt.subplots(figsize=(7, 3))
    ax.bar(list(averages.keys()), list(averages.values()))  # default colors
    ax.set_ylabel('Average Value')
    ax.set_title('Average Key Metrics')
    plt.xticks(rotation=20)
    return plot_to_base64(fig)

def make_pie_chart(labels, sizes, title):
    fig, ax = plt.subplots(figsize=(4, 4))
    ax.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=90)
    ax.set_title(title)
    return plot_to_base64(fig)

def df_to_summary_context(df, summary_stats, recovery_dist, sleep_debt_dist, low_recovery, high_sleep_debt):
    lines = []
    lines.append(f"Rows (days): {len(df)}")
    lines.append(f"Avg Recovery: {summary_stats['Recovery_score_']['mean']}")
    lines.append(f"Avg Rest HR (bpm): {summary_stats['Resting_heart_rate_(bpm)']['mean']}")
    lines.append(f"Avg HRV (ms): {summary_stats['Heart_rate_variability_(ms)']['mean']}")
    lines.append(f"Avg Sleep Perf: {summary_stats['Sleep_performance_']['mean']}")
    if "Sleep_debt_(min)" in df.columns:
        lines.append(f"Avg Sleep Debt (min): {round(df['Sleep_debt_(min)'].mean(),2)}")
        lines.append(f"High Sleep Debt Days (>100): {len(high_sleep_debt)}")
    lines.append(f"Recovery Dist Low/Med/High: {recovery_dist}")
    if sleep_debt_dist:
        lines.append(f"Sleep Debt Dist Low/Moderate/High: {sleep_debt_dist}")
    return "\n".join(lines)

def build_page_from_csv(csv_path, prompt_text=None, answer_text=None):
    """Load CSV, recompute visuals & summary, return all variables for template render."""
    df = pd.read_csv(csv_path)
    df.columns = df.columns.str.strip()

    summary = {
        "Recovery_score_": df["Recovery_score_"].describe(),
        "Resting_heart_rate_(bpm)": df["Resting_heart_rate_(bpm)"].describe(),
        "Heart_rate_variability_(ms)": df["Heart_rate_variability_(ms)"].describe(),
        "Sleep_performance_": df["Sleep_performance_"].describe(),
    }
    summary_stats = {k: v.round(2).to_dict() for k, v in summary.items()}
    avg_sleep_debt = round(df["Sleep_debt_(min)"].mean(), 2) if "Sleep_debt_(min)" in df else "N/A"

    # Counts & dists
    low_recovery = df[df["Recovery_score_"] < 50][["Cycle_start_time", "Recovery_score_"]] \
        if "Cycle_start_time" in df.columns else df[df["Recovery_score_"] < 50][["Recovery_score_"]]
    high_sleep_debt = (
        df[df["Sleep_debt_(min)"] > 100][["Cycle_start_time", "Sleep_debt_(min)"]]
        if "Sleep_debt_(min)" in df and "Cycle_start_time" in df.columns
        else df[df.get("Sleep_debt_(min)", pd.Series([])) > 100][["Sleep_debt_(min)"]]
        if "Sleep_debt_(min)" in df else pd.DataFrame()
    )
    low_recovery_count = len(low_recovery)
    high_sleep_debt_count = len(high_sleep_debt)
    total_days = len(df)

    # Charts
    averages = {
        "Recovery": round(df["Recovery_score_"].mean(), 2),
        "Rest HR": round(df["Resting_heart_rate_(bpm)"].mean(), 2),
        "HRV": round(df["Heart_rate_variability_(ms)"].mean(), 2),
        "Sleep Perf": round(df["Sleep_performance_"].mean(), 2),
        "Sleep Debt": round(df["Sleep_debt_(min)"].mean(), 2) if "Sleep_debt_(min)" in df else 0,
    }
    bar_chart = make_bar_chart(averages)

    pie_low_recovery = make_pie_chart(
        ["Low Recovery (<50)", "Normal/High"],
        [low_recovery_count, total_days - low_recovery_count],
        "Low Recovery Days"
    )
    pie_high_sleep_debt = make_pie_chart(
        ["High Sleep Debt (>100)", "Normal/Low"],
        [high_sleep_debt_count, total_days - high_sleep_debt_count],
        "High Sleep Debt Days"
    )

    recovery_dist = {
        "Low": int((df["Recovery_score_"] < 50).sum()),
        "Medium": int(((df["Recovery_score_"] >= 50) & (df["Recovery_score_"] < 80)).sum()),
        "High": int((df["Recovery_score_"] >= 80).sum())
    }
    if "Sleep_debt_(min)" in df:
        sleep_debt_dist = {
            "Low": int((df["Sleep_debt_(min)"] < 30).sum()),
            "Moderate": int(((df["Sleep_debt_(min)"] >= 30) & (df["Sleep_debt_(min)"] < 100)).sum()),
            "High": int((df["Sleep_debt_(min)"] >= 100).sum())
        }
    else:
        sleep_debt_dist = {"Low": 0, "Moderate": 0, "High": 0}

    # Highlights
    best_recovery = df.nlargest(3, "Recovery_score_")[["Cycle_start_time", "Recovery_score_"]] \
        if "Cycle_start_time" in df.columns else df.nlargest(3, "Recovery_score_")[["Recovery_score_"]]
    worst_recovery = df.nsmallest(3, "Recovery_score_")[["Cycle_start_time", "Recovery_score_"]] \
        if "Cycle_start_time" in df.columns else df.nsmallest(3, "Recovery_score_")[["Recovery_score_"]]
    best_recovery_html = best_recovery.to_html(index=False) if not best_recovery.empty else "<i>None</i>"
    worst_recovery_html = worst_recovery.to_html(index=False) if not worst_recovery.empty else "<i>None</i>"

    if "Sleep_debt_(min)" in df.columns:
        highest_sleep_debt = df.nlargest(3, "Sleep_debt_(min)")[["Cycle_start_time", "Sleep_debt_(min)"]] \
            if "Cycle_start_time" in df.columns else df.nlargest(3, "Sleep_debt_(min)")[["Sleep_debt_(min)"]]
        lowest_sleep_debt = df.nsmallest(3, "Sleep_debt_(min)")[["Cycle_start_time", "Sleep_debt_(min)"]] \
            if "Cycle_start_time" in df.columns else df.nsmallest(3, "Sleep_debt_(min)")[["Sleep_debt_(min)"]]
        highest_sleep_debt_html = highest_sleep_debt.to_html(index=False) if not highest_sleep_debt.empty else "<i>None</i>"
        lowest_sleep_debt_html = lowest_sleep_debt.to_html(index=False) if not lowest_sleep_debt.empty else "<i>None</i>"
    else:
        highest_sleep_debt_html = "<i>Not available</i>"
        lowest_sleep_debt_html = "<i>Not available</i>"

    # Build context (and store for reuse)
    context = df_to_summary_context(df, summary_stats, recovery_dist, sleep_debt_dist, low_recovery, high_sleep_debt)
    session["csv_path"] = csv_path
    session["summary_context"] = context

    # Return everything the template needs
    return dict(
        summary_stats=summary_stats,
        avg_sleep_debt=avg_sleep_debt,
        low_recovery_count=low_recovery_count,
        high_sleep_debt_count=high_sleep_debt_count,
        bar_chart=bar_chart,
        pie_low_recovery=pie_low_recovery,
        pie_high_sleep_debt=pie_high_sleep_debt,
        best_recovery_html=best_recovery_html,
        worst_recovery_html=worst_recovery_html,
        highest_sleep_debt_html=highest_sleep_debt_html,
        lowest_sleep_debt_html=lowest_sleep_debt_html,
        recovery_dist=recovery_dist,
        sleep_debt_dist=sleep_debt_dist,
        prompt=prompt_text or "",
        answer=answer_text or None
    )

def call_openai(context, prompt):
    if not client:
        return "[OpenAI not configured: set OPENAI_API_KEY in C:\\EUacademy\\.env]"
    try:
        try:
            resp = client.responses.create(
                model="gpt-4o-mini",
                input=[
                    {"role":"system","content":"You are a health & sleep coach. Be concise, numeric, and actionable."},
                    {"role":"user","content": f"Dataset summary:\n{context}\n\nUser prompt:\n{prompt}"}
                ],
                temperature=0.2
            )
            return resp.output_text.strip()
        except Exception:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role":"system","content":"You are a health & sleep coach. Be concise, numeric, and actionable."},
                    {"role":"user","content": f"Dataset summary:\n{context}\n\nUser prompt:\n{prompt}"}
                ],
                temperature=0.2
            )
            return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"[OpenAI error] {e}"

@app.route('/', methods=['GET', 'POST'])
def upload_file():
    # Branch A: prompt-only (reuse stored CSV/context)
    if request.method == 'POST' and ('file' not in request.files or request.files['file'].filename == ''):
        prompt = (request.form.get("prompt") or "").strip()
        csv_path = session.get("csv_path")
        context = session.get("summary_context")
        if not csv_path or not os.path.exists(csv_path):
            return render_template_string(HTML_FORM, error="Please upload a CSV first.")
        # Rebuild page from saved csv
        page_vars = build_page_from_csv(csv_path, prompt_text=prompt)
        if prompt:
            page_vars["answer"] = call_openai(context or "", prompt)
        return render_template_string(HTML_RESULT, **page_vars)

    # Branch B: fresh upload (parse + show + optionally call OpenAI in same request)
    error = None
    if request.method == 'POST' and 'file' in request.files:
        file = request.files['file']
        if file.filename == '':
            error = "No selected file"
            return render_template_string(HTML_FORM, error=error)
        if file and file.filename.endswith('.csv'):
            filename = secure_filename(file.filename)
            csv_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(csv_path)

            # Build the page and store context/path in session
            page_vars = build_page_from_csv(csv_path)

            # Optional: if a prompt is sent along with the upload (rare), answer it
            prompt = (request.form.get("prompt") or "").strip()
            if prompt:
                page_vars["prompt"] = prompt
                page_vars["answer"] = call_openai(session.get("summary_context",""), prompt)

            return render_template_string(HTML_RESULT, **page_vars)
        else:
            error = "Please upload a CSV file."
    # GET
    return render_template_string(HTML_FORM, error=error)

if __name__ == '__main__':
    app.run(host="127.0.0.1", port=5056, debug=True, use_reloader=False)
