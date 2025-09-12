from flask import Flask, render_template_string, request
import pandas as pd
import os
import matplotlib.pyplot as plt
import io
import base64
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

HTML_FORM = """
<!doctype html>
<title>Health & Sleep Data Analyzer</title>
<h2>Upload your physiological_cycles_today.csv</h2>
<form method=post enctype=multipart/form-data>
  <input type=file name=file accept=".csv">
  <input type=submit value=Upload>
</form>
{% if error %}
  <p style="color:red;">{{ error }}</p>
{% endif %}
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
  <tr>
    <th>Category</th>
    <th>Days</th>
  </tr>
  <tr>
    <td>Low (&lt;50)</td>
    <td>{{ recovery_dist['Low'] }}</td>
  </tr>
  <tr>
    <td>Medium (50-79)</td>
    <td>{{ recovery_dist['Medium'] }}</td>
  </tr>
  <tr>
    <td>High (&ge;80)</td>
    <td>{{ recovery_dist['High'] }}</td>
  </tr>
</table>

<h3>Sleep Debt Distribution</h3>
<table>
  <tr>
    <th>Category</th>
    <th>Days</th>
  </tr>
  <tr>
    <td>Low (&lt;30 min)</td>
    <td>{{ sleep_debt_dist['Low'] }}</td>
  </tr>
  <tr>
    <td>Moderate (30-100 min)</td>
    <td>{{ sleep_debt_dist['Moderate'] }}</td>
  </tr>
  <tr>
    <td>High (&ge;100 min)</td>
    <td>{{ sleep_debt_dist['High'] }}</td>
  </tr>
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
    ax.bar(averages.keys(), averages.values(), color=['#3498db', '#e67e22', '#27ae60', '#c0392b', '#8e44ad'])
    ax.set_ylabel('Average Value')
    ax.set_title('Average Key Metrics')
    plt.xticks(rotation=20)
    return plot_to_base64(fig)

def make_pie_chart(labels, sizes, colors, title):
    fig, ax = plt.subplots(figsize=(4, 4))
    ax.pie(sizes, labels=labels, autopct='%1.1f%%', colors=colors, startangle=90)
    ax.set_title(title)
    return plot_to_base64(fig)

@app.route('/', methods=['GET', 'POST'])
def upload_file():
    error = None
    if request.method == 'POST':
        if 'file' not in request.files:
            error = "No file part"
            return render_template_string(HTML_FORM, error=error)
        file = request.files['file']
        if file.filename == '':
            error = "No selected file"
            return render_template_string(HTML_FORM, error=error)
        if file and file.filename.endswith('.csv'):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            try:
                df = pd.read_csv(filepath)
                df.columns = df.columns.str.strip()
                # Compute summaries
                summary = {
                    "Recovery_score_": df["Recovery_score_"].describe(),
                    "Resting_heart_rate_(bpm)": df["Resting_heart_rate_(bpm)"].describe(),
                    "Heart_rate_variability_(ms)": df["Heart_rate_variability_(ms)"].describe(),
                    "Sleep_performance_": df["Sleep_performance_"].describe(),
                    "Asleep_duration_(min)": df["Asleep_duration_(min)"].describe(),
                    "Sleep_efficiency_": df["Sleep_efficiency_"].describe(),
                    "Sleep_consistency_": df["Sleep_consistency_"].describe(),
                    "Day_Strain": df["Day_Strain"].describe(),
                    "Energy_burned_(cal)": df["Energy_burned_(cal)"].describe(),
                }
                summary_stats = {k: v.round(2).to_dict() for k, v in summary.items()}
                avg_sleep_debt = round(df["Sleep_debt_(min)"].mean(), 2) if "Sleep_debt_(min)" in df else "N/A"
                # Low recovery and high sleep debt
                low_recovery = df[df["Recovery_score_"] < 50][["Cycle_start_time", "Recovery_score_"]]
                high_sleep_debt = df[df["Sleep_debt_(min)"] > 100][["Cycle_start_time", "Sleep_debt_(min)"]]
                low_recovery_count = len(low_recovery)
                high_sleep_debt_count = len(high_sleep_debt)
                total_days = len(df)
                # Bar chart for averages
                averages = {
                    "Recovery": round(df["Recovery_score_"].mean(), 2),
                    "Rest HR": round(df["Resting_heart_rate_(bpm)"].mean(), 2),
                    "HRV": round(df["Heart_rate_variability_(ms)"].mean(), 2),
                    "Sleep Perf": round(df["Sleep_performance_"].mean(), 2),
                    "Sleep Debt": round(df["Sleep_debt_(min)"].mean(), 2) if "Sleep_debt_(min)" in df else 0,
                }
                bar_chart = make_bar_chart(averages)
                # Pie chart for low recovery
                pie_low_recovery = make_pie_chart(
                    ["Low Recovery (<50)", "Normal/High"],
                    [low_recovery_count, total_days - low_recovery_count],
                    ["#c0392b", "#27ae60"],
                    "Low Recovery Days"
                )
                # Pie chart for high sleep debt
                pie_high_sleep_debt = make_pie_chart(
                    ["High Sleep Debt (>100)", "Normal/Low"],
                    [high_sleep_debt_count, total_days - high_sleep_debt_count],
                    ["#e67e22", "#3498db"],
                    "High Sleep Debt Days"
                )
                # Recovery score distribution
                recovery_dist = {
                    "Low": int((df["Recovery_score_"] < 50).sum()),
                    "Medium": int(((df["Recovery_score_"] >= 50) & (df["Recovery_score_"] < 80)).sum()),
                    "High": int((df["Recovery_score_"] >= 80).sum())
                }
                # Sleep debt distribution
                if "Sleep_debt_(min)" in df:
                    sleep_debt_dist = {
                        "Low": int((df["Sleep_debt_(min)"] < 30).sum()),
                        "Moderate": int(((df["Sleep_debt_(min)"] >= 30) & (df["Sleep_debt_(min)"] < 100)).sum()),
                        "High": int((df["Sleep_debt_(min)"] >= 100).sum())
                    }
                else:
                    sleep_debt_dist = {"Low": 0, "Moderate": 0, "High": 0}
                # Highlights
                best_recovery = df.nlargest(3, "Recovery_score_")[["Cycle_start_time", "Recovery_score_"]]
                worst_recovery = df.nsmallest(3, "Recovery_score_")[["Cycle_start_time", "Recovery_score_"]]
                best_recovery_html = best_recovery.to_html(index=False) if not best_recovery.empty else "<i>None</i>"
                worst_recovery_html = worst_recovery.to_html(index=False) if not worst_recovery.empty else "<i>None</i>"
                if "Sleep_debt_(min)" in df:
                    highest_sleep_debt = df.nlargest(3, "Sleep_debt_(min)")[["Cycle_start_time", "Sleep_debt_(min)"]]
                    lowest_sleep_debt = df.nsmallest(3, "Sleep_debt_(min)")[["Cycle_start_time", "Sleep_debt_(min)"]]
                    highest_sleep_debt_html = highest_sleep_debt.to_html(index=False) if not highest_sleep_debt.empty else "<i>None</i>"
                    lowest_sleep_debt_html = lowest_sleep_debt.to_html(index=False) if not lowest_sleep_debt.empty else "<i>None</i>"
                else:
                    highest_sleep_debt_html = "<i>Not available</i>"
                    lowest_sleep_debt_html = "<i>Not available</i>"
                return render_template_string(
                    HTML_RESULT,
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
                    sleep_debt_dist=sleep_debt_dist
                )
            except Exception as e:
                error = f"Error processing file: {e}"
                return render_template_string(HTML_FORM, error=error)
        else:
            error = "Please upload a CSV file."
    return render_template_string(HTML_FORM, error=error)

if __name__ == '__main__':
    app.run(host="127.0.0.1", port=5050, debug=True) 