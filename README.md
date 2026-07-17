# 📦 Smart Inventory & Supplier Agent

An AI agent that checks stock, drafts supplier emails, and finds new suppliers online — built with LangGraph and wrapped in a mobile-friendly Streamlit app.

## The idea

Most inventory checks happen in two places: on a laptop at a desk, or on a phone while walking around a store/garage checking shelves. This project tries to cover both.

You can type a request like *"I need Dettol 100g"*, or just take a photo of a product label from your phone. The agent then:

1. Reads the product name and size from your text or image
2. Checks the current stock in the database
3. If stock is low and a supplier email is already on file → drafts a purchase order email automatically
4. If no supplier email is on file → searches the web and shows you the best supplier options with price and rating
5. Lets you review the result and decide to send the email, revise it, or search for more options, before anything actually goes out

If the product isn't in the database yet, it asks you to register it first, so nothing gets lost.

## Demo

- https://inventory-system-management.streamlit.app/

## Tech stack

- **LangGraph** — the agent's workflow (extraction → stock check → email or search → human review), built as a proper state graph, not a single prompt
- **Gemini** — extracts product name and quantity from text or images
- **Groq** — drafts the supplier email and picks the best suppliers from search results
- **Tavily** — searches Amazon, Walmart, and eBay for suppliers when needed
- **SQLite** — stores the product inventory
- **Streamlit** — the interface, including live camera capture for mobile use

## How it works (high level)

```
User input (text or photo)
        ↓
Extract product name + quantity  (Gemini)
        ↓
Check stock in SQLite
        ↓
   ┌────┴────┐
Stock low +      Stock low +
email on file    no email on file
   ↓                  ↓
Draft email      Search suppliers
(Groq)           online (Tavily + Groq)
   ↓                  ↓
   └──── Human reviews result ────┘
        ↓
  Satisfied → send email / end session
  Not satisfied → revise & try again
```

## Getting started

```bash
git clone <your-repo-url>
cd inventory-agent
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and add your keys:

```
api_key=your_gemini_api_key
tavil=your_tavily_api_key
GROQ_API_KEY=your_groq_api_key
SENDER_EMAIL=your_gmail_address
SENDER_PASSWORD=your_gmail_app_password
```

Run it:

```bash
streamlit run app.py
```

The app opens in your browser. For phone camera access, serve it over HTTPS (for example with `ngrok http 8501`) and open that link on your phone.

## Project structure

```
inventory_agent.py   -> all backend logic: extraction, stock check, email, supplier search, LangGraph workflow
app.py                -> Streamlit interface (dashboard, add product, smart agent)
requirements.txt
.env.example
.streamlit/config.toml -> app theme
```

## Known limitations

- Stock quantity isn't reduced automatically after an order is sent — right now the agent notifies, it doesn't yet update inventory on confirmed orders
- Meant as a working prototype, not hardened for production (no auth, no logging, plaintext env vars)
- SMTP sending currently only supports Gmail app passwords

## Possible next steps

- Auto-update stock once an order is confirmed
- Order history / tracking
- Multi-user support
- Deploy version with proper secrets management

## Author

Built as a personal project to explore agentic workflows with LangGraph beyond simple chatbots.
