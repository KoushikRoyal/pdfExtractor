import streamlit as st
import pdfplumber
import requests
import json
import re
import tempfile
import pandas as pd

st.set_page_config(page_title="Financial Data Extractor", layout="wide")
st.title("📊 Financial Data Extractor from Equity Research PDFs")

# --- API Key ---
API_KEY = st.text_input("🔑 Enter Gemini API Key", type="password")

# --- Upload PDFs ---
uploaded_files = st.file_uploader("📂 Upload one or more Equity Research PDFs", type="pdf", accept_multiple_files=True)

def extract_text_and_tables(pdf_path):
    full_text = ""
    all_tables = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            full_text += f"\n--- Page {i + 1} Text ---\n{text if text else '[No text found]'}"
            tables = page.extract_tables()
            if tables:
                for t_index, table in enumerate(tables):
                    full_text += f"\n--- Page {i + 1} Table {t_index + 1} ---\n"
                    for row in table:
                        row_text = " | ".join(cell if cell else "" for cell in row)
                        full_text += row_text + "\n"
                    all_tables.append(table)
    return full_text, all_tables

def create_prompt(text_content):
    return f"""
You are a financial data extractor.

From the content below, extract and return this JSON object:

{{
  "reviewer": "",
  "reviewee": "",
  "analyst": "",
  "analystMail": "",
  "analystPhone": "",
  "rating": "",
  "current_price": "",
  "target_price": "",
  "previous_target": "",
  "comments": "",
  "revenueFY24E": "",
  "ebitdaFY24E": "",
  "ebitdaMarginFY24E": "",
  "patFY24E": "",
  "revenueFY25E": "",
  "ebitdaFY25E": "",
  "ebitdaMarginFY25E": "",
  "patFY25E": "",
  "revenue3QFY24": "",
  "ebitda3QFY24": "",
  "ebitda3QFY24yoy": "",
  "ebitda3QFY24qoq": "",
  "ebitdaMargin3QFY24": "",
  "pat3QFY24": "",
  "pat3QFY24yoy": "",
  "pat3QFY24qoq": ""
}}

Accept label variations such as:
- Give the name of the company that has produced or written this review under the key "reviewer"
- Give the name of the company about which this report is written about under the key "reviewee"
- Give the full name of the analyst that written the report under the key "analyst". In case of multiple analysts, give only the first person.
- Give the email of the analyst under the key "analystMail". Include all special characters.
- Give the phone number of the analyst under the key "analystPhone". Include '+' and space in place of '-'.
- Extract stock rating terms like: buy, sell, hold, add, reduce, overweight, neutral under "rating"
- "CMP","Price Now","Current Market Price" → current_price
- "TP","Target","Target Price" → target_price
- "Previous TP","PT" → previous_target
- If "Retain/maintain rating" → comments = "Maintain Rating". If changed, write as "Rating changged to (new rating)"

Look for revenue/EBITDA/PAT values in tables with rows like:
- Revenue, Sales → revenueFY24E, revenueFY25E, revenue3QFY24
- EBITDA → ebitdaFY24E, ebitdaFY25E, ebitda3QFY24
- PAT, Profit after tax → patFY24E, patFY25E, pat3QFY24
- EBITDA margin, EBITDS margin % → ebitdaMarginFY24E, etc.
- YoY/QoQ fields → like "EBITDA YoY", "PAT QoQ"

Clean all values:
- Only keep digits, negative signs, or decimal points
- For example, "-1.2 3%(7)" → "-1.23"

If value is in USD, convert it to INR (1 USD = 85.71) → then to billions

Return **only a valid JSON object**. Do not explain. Do not wrap in code blocks.

PDF Content:
\"\"\"
{text_content}
\"\"\"
"""


def query_gemini(prompt, api_key):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    data = {"contents": [{"parts": [{"text": prompt}]}]}
    response = requests.post(url, headers=headers, json=data)
    if response.ok:
        try:
            return response.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            st.error(f"Parsing Gemini response failed: {e}")
    else:
        st.error(f"Gemini API Error: {response.status_code}")
        st.text(response.text)
    return None

def parse_json_response(result):
    cleaned = re.sub(r"```json|```", "", result).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        st.error("JSON parse error")
        st.text(result)
        return None

# --- Process PDFs ---
if uploaded_files and API_KEY:
    all_text = ""
    all_tables_combined = []

    for file in uploaded_files:
        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            tmp_file.write(file.read())
            pdf_path = tmp_file.name
        text_content, table_data = extract_text_and_tables(pdf_path)
        all_text += text_content + "\n\n"
        all_tables_combined.extend(table_data)

    # --- Editable Prompt ---
    st.subheader("✍️ Editable Prompt Preview")
    default_prompt = create_prompt(all_text)
    user_prompt = st.text_area("📝 Modify Prompt if Needed", value=default_prompt, height=400)

    if st.button("🔮 Send to Gemini & Extract JSON"):
        with st.spinner("🔍 Extracting with Gemini..."):
            result = query_gemini(user_prompt, API_KEY)
            if result:
                final_json = parse_json_response(result)
                if final_json:
                    st.success("✅ JSON Extracted Successfully!")
                    st.json(final_json)

                    # 📥 Download JSON
                    json_str = json.dumps(final_json, indent=2)
                    st.download_button(
                        label="📥 Download JSON Output",
                        data=json_str,
                        file_name="financial_data.json",
                        mime="application/json"
                    )
                else:
                    st.error("❌ Couldn't convert to JSON.")

    # --- Display Tables ---
    if all_tables_combined:
        st.subheader("📊 Extracted Tables (Preview)")

        for i, table in enumerate(all_tables_combined):
            try:
                df = pd.DataFrame(table)
                if df.dropna(how="all").dropna(axis=1, how="all").empty:
                    continue
                st.write(f"📄 Table {i + 1}")
                st.dataframe(df)

                # 📈 Try plotting numeric columns
                try:
                    numeric_df = df.apply(pd.to_numeric, errors='coerce')
                    numeric_df = numeric_df.dropna(axis=1, how='all').dropna(how='all')
                    if not numeric_df.empty:
                        st.line_chart(numeric_df)
                except:
                    pass
            except Exception as e:
                st.warning(f"Could not render Table {i+1}: {e}")
