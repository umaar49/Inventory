import os
import json
import sqlite3
import re

from google import genai
from google.genai import types
from dotenv import load_dotenv
from typing import TypedDict, Optional, Literal
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from tavily import TavilyClient
from groq import Groq

import smtplib
from email.mime.text import MIMEText

load_dotenv()
api_key = os.getenv("tavil")
tavily_api_key = api_key.replace("\n", "").replace(" ", "").strip("'\"") if tavily_raw else None
client = TavilyClient(tavily_api_key)

groq_raw = os.getenv("GROQ_API_KEY")
groq_api_key = groq_raw.replace("\n", "").replace(" ", "").strip("'\"") if groq_raw else None
grok_client = Groq(
    api_key=os.environ.get(groq_api_key),
)
model_name = "gemini-3.1-flash-lite"

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Supplier.db")


class AgentState(TypedDict):
    """State that flows through our LangGraph agent"""
    user_input: str
    input_type: Literal["text", "image"]
    extracted_product: Optional[dict]
    stock_info: Optional[dict]
    supplier_recommendations: Optional[dict]
    user_choice: Optional[str]
    supplier_email: Optional[str]
    order_quantity: Optional[str]
    supplier_name: Optional[str]
    final_message: str


PRODUCT_EXTRACTION_PROMPT = """
You are a product extraction agent for an inventory management system.
Your extraction MUST be consistent: the same real-world product should always
produce the exact same "product_name", no matter how the user phrases it.

Extract exactly two fields from the user query:

1. "product_name" - ONLY the brand/product name, and nothing else.
   - Strip out generic container / packaging / unit words such as:
     bottle, bottles, pack, packet, packaging, box, can, jar, tube, bag,
     container, piece, pcs, unit, units, sachet, roll, carton.
   - Strip filler words such as: a, an, the, some, need, want, please, give me, of.
   - Do NOT include any size, weight, volume, or count in product_name.
   - Normalize to Title Case (e.g. "dettol" -> "Dettol", "DETTOL" -> "Dettol").
   - If the brand/product name has multiple words, keep all of them, but still
     Title Case them and still strip packaging/filler words.

2. "quantity" - the size/weight/volume mentioned in the query, formatted as a
   short string like "100 g", "3 LTR", "2 kg". If no size is mentioned in the
   query, return an empty string "" for quantity (do not guess a number).

Return STRICT JSON only, with no markdown, no code fences, no explanation.
Schema: {{"product_name": "string", "quantity": "string"}}

Examples (these show why normalization matters - the SAME product must map
to the SAME product_name every time):
Query: "I need Dettol 100 g"            -> {{"product_name": "Dettol", "quantity": "100 g"}}
Query: "dettol 100g bottle"             -> {{"product_name": "Dettol", "quantity": "100 g"}}
Query: "give me a bottle of dettol"     -> {{"product_name": "Dettol", "quantity": ""}}
Query: "2kg pack of detergent"          -> {{"product_name": "Detergent", "quantity": "2 kg"}}
Query: "phenyle 3 ltr can"              -> {{"product_name": "Phenyle", "quantity": "3 LTR"}}
Query: "bleach"                         -> {{"product_name": "Bleach", "quantity": ""}}

User Query: {query}
"""


def _normalize_product_name(name: str) -> str:
    """Safety net so the DB key stays consistent even if the LLM is ever
    inconsistent - strips common packaging words and normalizes casing/spacing."""
    if not name:
        return name
    packaging_words = {
        "bottle", "bottles", "pack", "packet", "packaging", "box", "can",
        "jar", "tube", "bag", "container", "piece", "pcs", "unit", "units",
        "sachet", "roll", "carton"
    }
    tokens = [t for t in re.split(r"\s+", name.strip()) if t.lower() not in packaging_words]
    cleaned = " ".join(tokens) if tokens else name.strip()
    return cleaned.strip().title()


def extract_from_text(query: str) -> dict:
    """Extract product info from text query. Returns dict."""
    client = genai.Client(api_key=os.getenv("api_key"))
    base_statement = PRODUCT_EXTRACTION_PROMPT.format(query=query)
    response = client.models.generate_content(
        model=model_name,
        contents=base_statement,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    try:
        result_dict = json.loads(response.text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse Gemini response as JSON: {e}")

    if result_dict.get("product_name"):
        result_dict["product_name"] = _normalize_product_name(result_dict["product_name"])
    return result_dict


def extract_from_image(image_path: str) -> dict:
    """Extract product info from image. Returns dict."""
    client = genai.Client(api_key=os.getenv("api_key"))

    base_statement = """
    You are an inventory monitoring agent. Look closely at this image.
    Extract exactly two fields:

    1. "product_name" - ONLY the brand/product name visible on the label.
       - Strip out generic container/packaging words such as: bottle, bottles,
         pack, packet, box, can, jar, tube, bag, container, piece, pcs, unit,
         sachet, roll, carton.
       - Do NOT include any size, weight, volume, or count in product_name.
       - Normalize to Title Case (e.g. "DETTOL" -> "Dettol").
       - The same real-world product must always map to the same product_name,
         regardless of how it's written on the label.

    2. "quantity" - the size/weight/volume written on the image, formatted as
       a short string like "100 g", "3 LTR", "2 kg". If none is visible,
       return an empty string "".

    Return STRICT JSON only, matching this schema exactly, no markdown, no explanation:
    {"product_name": "string", "quantity": "string"}
    """

    try:
        with open(image_path, "rb") as f:
            image_bytes = f.read()
    except FileNotFoundError:
        raise FileNotFoundError(f"File '{image_path}' not found.")

    response = client.models.generate_content(
        model=model_name,
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
            base_statement
        ],
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )

    try:
        result_dict = json.loads(response.text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse Gemini response as JSON: {e}")

    if result_dict.get("product_name"):
        result_dict["product_name"] = _normalize_product_name(result_dict["product_name"])
    return result_dict


def create_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT UNIQUE NOT NULL,
            bottle_size TEXT,
            quantity_left INTEGER DEFAULT 0,
            supplier_email TEXT DEFAULT NULL,
            supplier_name TEXT DEFAULT NULL
        )
    ''')

    conn.commit()
    conn.close()


def add_product(product_name, bottle_size, quantity_left, supplier_email=None, supplier_name=None):
    product_name = _normalize_product_name(product_name)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        INSERT OR REPLACE INTO products (product_name, bottle_size, quantity_left, supplier_email, supplier_name)
        VALUES (?, ?, ?, ?, ?)
    ''', (product_name, bottle_size, quantity_left, supplier_email, supplier_name))

    conn.commit()
    conn.close()


def delete_product(product_name):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM products WHERE product_name = ?', (product_name,))
    conn.commit()
    conn.close()


def get_all_products():
    """Used by the Streamlit dashboard to list every product."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT product_name, bottle_size, quantity_left, supplier_email, supplier_name FROM products')
    rows = cursor.fetchall()
    conn.close()
    return rows


def _seed_sample_data_if_empty():
    """Same 4 sample products from your original script, but only inserted
    once (when the table is empty) so Streamlit reruns don't keep resetting
    your data."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM products")
    count = cursor.fetchone()[0]
    conn.close()

    if count == 0:
        add_product("Phenyle", "3 LTR", 30, "phenylesupplier@gmail.com", "John")
        add_product("Bleach", "5 LTR", 15)
        add_product("Detergent", "2 kg", 25, "detergentsupplier@gmail.com", "Wick")
        add_product("Dettol", "100 g", 5, "ug@gmail.com", "Eric")


create_database()
_seed_sample_data_if_empty()


def check_stock(product_name: str) -> dict:
    """Check stock from database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT product_name, bottle_size, quantity_left, supplier_email, supplier_name
        FROM products
        WHERE product_name = ?
    ''', (product_name,))

    result = cursor.fetchone()
    conn.close()

    if result:
        return {
            'product_name': result[0],
            'bottle_size': result[1],
            'quantity_left': result[2],
            'supplier_email': result[3],
            'supplier_name': result[4]
        }
    else:
        return None


def generate_email(product_name, bottle_size, order_quantity, supplier_email, supplier_name):
    """Generate professional email using LLM"""

    prompt = f"""
    You are an automated supply chain assistant writing a formal purchase order email.

    Context Details:
    - Supplier Name to address: {supplier_name}
    - Supplier Contact Email: {supplier_email}
    - Product Required: {product_name}
    - Product Unit Size: {bottle_size}
    - Order Volume: {order_quantity} units

    CRITICAL OUTPUT CONSTRAINTS:
    1. Output the email in plain text ONLY. No markdown formatting.
    2. DO NOT use asterisks (**), hashtags (#), or underlines (_).
    3. The greeting must strictly address the supplier name "{supplier_name}". DO NOT write the raw email address in the greeting line (e.g., do NOT write "Dear {supplier_email}").

    Ensure the email includes a concise subject line, a professional greeting addressing {supplier_name}, and a clear call to action regarding order confirmation.

    At the bottom of the email, below "Best regards,", always append these exact details:
    Company Name: CogLix
    Email: coglixofficial@gmail.com
    """

    response = grok_client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1
    )
    return response.choices[0].message.content


def send_email_to_supplier(to_email, email_body, product_name):
    """Sends the drafted email via SMTP."""
    sender_email = os.getenv("SENDER_EMAIL")
    sender_password = os.getenv("SENDER_PASSWORD")

    msg = MIMEText(email_body)
    msg['Subject'] = f"Urgent Stock Purchase Order: {product_name}"
    msg['From'] = sender_email
    msg['To'] = to_email

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, to_email, msg.as_string())
        return True, "Email successfully sent to the supplier!"
    except Exception as e:
        return False, f"Failed to send email: {e}"


def extract_price_from_content(content: str) -> str:
    """Extract first price found in text"""
    match = re.search(r'\$\d+(?:\.\d{2})?', content)
    if match:
        return match.group(0)
    else:
        return "Price not found"


def search_suppliers(product_name: str, bottle_size: str) -> dict:
    search_query = f"{product_name} {bottle_size} wholesale bulk supplier price"
    search_result = client.search(
        query=search_query,
        search_depth="advanced",
        include_domains=["amazon.com", "walmart.com", "ebay.com"],
        max_results=10,
        include_answer=True,
        include_raw_content=True
    )
    search_context = []
    for result in search_result['results']:
        search_context.append({
            'title': result['title'],
            'url': result['url'],
            'content': result['content'],
            'score': result['score']
        })

    sorted_results = sorted(search_context, key=lambda x: x['score'], reverse=True)
    good_results = [r for r in sorted_results if r['score'] >= 0.4]
    clean_results = []
    for r in good_results[:5]:
        clean_results.append({
            'title': r['title'],
            'url': r['url'],
            'price_hint': extract_price_from_content(r['content']),
            'score': r['score']
        })
    prompt = f"""
    You are a procurement agent. Analyze these search results for {product_name} ({bottle_size}).
    Search Results:
    {clean_results}
    Extract the top 3 best suppliers based on:
    1. Price (best value)
    2. Reviews/ratings
    3. Reliability signals
    Return ONLY a JSON dict with this structure:
    {{
        "product": "{product_name}",
        "size": "{bottle_size}",
        "suppliers": [
            {{
                "name": "supplier name",
                "source": "website name",
                "price": "price info",
                "reviews": "rating or review summary",
                "url": "product URL",
                "reason_to_buy": "why this is a good choice"
            }}
        ]
    }}
    """
    response = grok_client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[
            {"role": "system", "content": "You extract supplier information from search results. Return only valid JSON."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.1,
        reasoning_effort="medium"
    )
    supplier_info = json.loads(response.choices[0].message.content)
    return supplier_info


def extract_product_node(state: AgentState) -> AgentState:
    """Extract product info from either text or image based on input_type"""
    if state["input_type"] == "text":
        extracted = extract_from_text(state["user_input"])
    elif state["input_type"] == "image":
        extracted = extract_from_image(state["user_input"])
    else:
        raise ValueError(f"Unknown input_type: {state['input_type']}")
    return {"extracted_product": extracted}


def check_database_node(state: AgentState) -> dict:
    """NOTE: unlike your original CLI version, this node no longer prompts
    with input() to register a missing product (a web server can't block on
    terminal input). If the product is missing, app.py registers it via a
    Streamlit form BEFORE the agent graph is invoked, so by the time this
    node runs the product already exists."""
    extracted = state.get("extracted_product", {})
    product_name = extracted.get("product_name")

    if not product_name:
        return {"stock_info": None}

    stock_info = check_stock(product_name)
    return {"stock_info": stock_info}


def email_draft_node(state: AgentState) -> dict:
    extracted = state.get("extracted_product", {})
    stock_info = state.get("stock_info", {}) or {}
    product = extracted.get("product_name", "Product")

    bottle_size = stock_info.get("bottle_size") or extracted.get("quantity") or "N/A"
    email = stock_info.get("supplier_email")

    if not email:
        return {"supplier_recommendations": None}

    name = stock_info.get("supplier_name")

    if not name:
        try:
            domain = email.split("@")[1].split(".")[0]
            name = f"{domain.capitalize()} Team"
        except Exception:
            name = "Supplier Team"

    qty = state.get("order_quantity") or "50"

    email_content = generate_email(product, bottle_size, qty, email, supplier_name=name)

    return {
        "final_message": email_content,
        "supplier_email": email,
        "stock_info": stock_info
    }


def check_db_results(state: AgentState) -> str:
    """Routes the graph depending on whether a supplier email was found in the DB."""
    stock_info = state.get("stock_info")
    if stock_info and stock_info.get("supplier_email"):
        return "has_email"
    else:
        return "no_email"


def find_suppliers_node(state: AgentState) -> AgentState:
    """Search for suppliers when stock is low"""
    product_name = state["extracted_product"]["product_name"]
    bottle_size = state["extracted_product"]["quantity"]
    stock_info = state["stock_info"]
    if stock_info is None:
        return {"supplier_recommendations": None}
    quantity_left = stock_info["quantity_left"]
    if quantity_left <= 10:
        supplier_results = search_suppliers(product_name, bottle_size)
        return {"supplier_recommendations": supplier_results}
    else:
        return {"supplier_recommendations": None}


def should_continue(state: AgentState) -> str:
    user_choice = state.get("user_choice", "")
    if user_choice is None:
        user_choice = ""
    else:
        user_choice = str(user_choice).lower().strip()

    if user_choice == "end" or user_choice == "":
        return "end"

    stock_info = state.get("stock_info")
    if stock_info and stock_info.get("supplier_email"):
        return "rewrite_email"
    else:
        return "continue_search"


def find_more_suppliers_node(state: AgentState) -> AgentState:
    """Search for additional suppliers (different query or more results)"""
    extracted = state["extracted_product"]
    product_name = extracted["product_name"]
    bottle_size = extracted["quantity"]

    supplier_results = search_suppliers(product_name, bottle_size)

    return {"supplier_recommendations": supplier_results}


def final_response_node(state: AgentState) -> AgentState:
    """Generate final message with stock info and supplier recommendations"""
    extracted = state["extracted_product"]
    stock_info = state["stock_info"]
    supplier_rec = state.get("supplier_recommendations")

    product_name = extracted["product_name"]
    requested_size = extracted["quantity"]

    message_parts = []
    message_parts.append(f"📦 Product: {product_name}")
    message_parts.append(f"Requested Size: {requested_size}")
    message_parts.append("")

    if stock_info is None:
        message_parts.append("❌ Product not found in inventory database")
    else:
        stock_qty = stock_info["quantity_left"]
        stock_size = stock_info["bottle_size"]

        if requested_size == stock_size:
            message_parts.append(f"✅ Size: {stock_size} (matches request)")
        else:
            message_parts.append(f"⚠️ Size mismatch: We have {stock_size}")

        if stock_qty > 0:
            message_parts.append(f"📊 Stock remaining: {stock_qty} bottles")

            if stock_qty <= 10 and supplier_rec and supplier_rec.get('suppliers'):
                message_parts.append("")
                message_parts.append("⚠️ **LOW STOCK ALERT!** ⚠️")
                message_parts.append(f"Only {stock_qty} bottles remaining!")
                message_parts.append("")
                message_parts.append("📦 **SUPPLIER RECOMMENDATIONS:**")
                message_parts.append("")

                for i, supplier in enumerate(supplier_rec['suppliers'], 1):
                    message_parts.append(f"{i}. **{supplier['name']}** ({supplier['source']})")
                    message_parts.append(f"   💰 Price: {supplier['price']}")
                    message_parts.append(f"   ⭐ Rating: {supplier['reviews']}")
                    message_parts.append(f"   🔗 URL: {supplier['url']}")
                    message_parts.append(f"   💡 {supplier['reason_to_buy']}")
                    message_parts.append("")
            elif stock_qty <= 10:
                message_parts.append("⚠️ LOW STOCK! Run supplier search to find deals.")
            else:
                message_parts.append("✅ Stock level is healthy")
        else:
            message_parts.append("❌ **OUT OF STOCK** ❌")

    final_message = "\n".join(message_parts)
    return {"final_message": final_message}


workflow = StateGraph(AgentState)

workflow.add_node("extract_product", extract_product_node)
workflow.add_node("check_database", check_database_node)
workflow.add_node("Supplier_email", email_draft_node)
workflow.add_node("find_suppliers", find_suppliers_node)
workflow.add_node("final_response", final_response_node)
workflow.add_node("find_more", find_more_suppliers_node)

workflow.set_entry_point("extract_product")
workflow.add_edge("extract_product", "check_database")

workflow.add_conditional_edges(
    "check_database",
    check_db_results,
    {
        "has_email": "Supplier_email",
        "no_email": "find_suppliers"
    }
)

workflow.add_edge("find_suppliers", "final_response")

workflow.add_conditional_edges(
    "Supplier_email",
    should_continue,
    {
        "rewrite_email": "Supplier_email",
        "end": END
    }
)
workflow.add_conditional_edges(
    "final_response",
    should_continue,
    {
        "continue_search": "find_more",
        "end": END
    }
)

workflow.add_edge("find_more", "find_suppliers")

memory = MemorySaver()
agent = workflow.compile(
    checkpointer=memory,
    interrupt_after=["Supplier_email", "final_response"]
)
