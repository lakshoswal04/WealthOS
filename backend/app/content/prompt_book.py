"""The Prompt Book: how to ask the assistant for what it can actually do.

Every example names the tool it should reach (`tool`); a test sends each
prompt through the assistant's planner and checks it lands there, so the
book cannot promise something the assistant does not do. Page copy has a
Hindi translation; prompts stay in English because the assistant routes
English text.
"""

from __future__ import annotations

HERO = {
    "en": {"eyebrow": "Prompt book", "title_1": "Write better prompts.", "title_2a": "Get ",
           "title_2b": "better results", "title_2c": " from", "title_3": "WealthOS AI.",
           "lede": "Your step-by-step guide to talking to the assistant: from your first backtest "
                   "to deploying Autopilot on paper."},
    "hi": {"eyebrow": "प्रॉम्प्ट बुक", "title_1": "बेहतर प्रॉम्प्ट लिखें।", "title_2a": "पाएँ ",
           "title_2b": "बेहतर नतीजे", "title_2c": "", "title_3": "WealthOS AI से।",
           "lede": "असिस्टेंट से बात करने की आपकी चरण-दर-चरण गाइड: पहले बैकटेस्ट से लेकर "
                   "पेपर पर ऑटोपायलट चलाने तक।"},
}

CHAPTERS = [
    {
        "slug": "backtesting", "number": 1, "level": 2, "icon": "clock",
        "en": {"title": "Backtesting prompts", "badge": "Beginner friendly",
               "summary": "Test a strategy on two years of history before you trade it.",
               "principles": ["Name the strategy: EMA crossover, RSI mean reversion, golden cross, "
                              "52-week breakout, MACD momentum, gap and go, inside-day breakout.",
                              "Name the stock or index to test it on.",
                              "Compare against buy and hold, which every result shows."]},
        "hi": {"title": "बैकटेस्टिंग प्रॉम्प्ट", "badge": "शुरुआती के लिए",
               "summary": "ट्रेड करने से पहले किसी रणनीति को दो साल के इतिहास पर परखें।",
               "principles": ["रणनीति का नाम लिखें: EMA क्रॉसओवर, RSI मीन रिवर्जन, गोल्डन क्रॉस, "
                              "52-हफ़्ते ब्रेकआउट, MACD मोमेंटम, गैप एंड गो, इनसाइड-डे ब्रेकआउट।",
                              "जिस शेयर या इंडेक्स पर परखना है उसका नाम लिखें।",
                              "हर नतीजे में दिखने वाले बाय-एंड-होल्ड से तुलना करें।"]},
        "examples": [
            {"prompt": "Backtest the RSI mean reversion strategy on INFY", "tool": "run_backtest"},
            {"prompt": "Backtest a golden cross on HDFCBANK", "tool": "run_backtest"},
            {"prompt": "Backtest the 52-week breakout on BHARTIARTL", "tool": "run_backtest"},
            {"prompt": "Backtest gap and go on RELIANCE", "tool": "run_backtest"},
        ],
        "vague": [{"prompt": "Is trading profitable?",
                   "why": "No strategy and no stock: there is nothing to test."}],
    },
    {
        "slug": "research", "number": 2, "level": 3, "icon": "search",
        "en": {"title": "Research prompts", "badge": "Intermediate",
               "summary": "Prices, movers, screens and rule-based ideas, in plain language.",
               "principles": ["Use the NSE symbol (RELIANCE, HDFCBANK) or the company name.",
                              "Ask for one thing at a time: a price, a screen, or ideas.",
                              "Screens look at the NIFTY 100; ideas are rule-based, not advice."]},
        "hi": {"title": "रिसर्च प्रॉम्प्ट", "badge": "मध्यम स्तर",
               "summary": "भाव, मूवर्स, स्क्रीन और नियम-आधारित आइडिया, आसान भाषा में।",
               "principles": ["NSE सिंबल (RELIANCE, HDFCBANK) या कंपनी का नाम लिखें।",
                              "एक बार में एक चीज़ पूछें: भाव, स्क्रीन या आइडिया।",
                              "स्क्रीन NIFTY 100 पर चलती हैं; आइडिया नियम-आधारित हैं, सलाह नहीं।"]},
        "examples": [
            {"prompt": "How is RELIANCE doing today?", "tool": "get_quote"},
            {"prompt": "Which stocks are near their 52-week high?", "tool": "run_screener"},
            {"prompt": "Show me oversold stocks", "tool": "run_screener"},
            {"prompt": "What are the top losers today?", "tool": "get_market_movers"},
            {"prompt": "Give me delivery ideas", "tool": "get_ideas"},
        ],
        "vague": [{"prompt": "What should I do?", "why": "No subject: name a stock, a screen or a kind of idea."}],
    },
    {
        "slug": "paper-trading", "number": 3, "level": 4, "icon": "bolt",
        "en": {"title": "Paper trading prompts", "badge": "Advanced",
               "summary": "Place practice orders at real prices. Nothing is placed until you confirm.",
               "principles": ["Say buy or sell, the quantity, and the symbol.",
                              "For options say lots, the index, the strike and CE or PE.",
                              "The assistant proposes; you press Confirm. Orders stay on paper."]},
        "hi": {"title": "पेपर ट्रेडिंग प्रॉम्प्ट", "badge": "उन्नत",
               "summary": "असली भाव पर अभ्यास ऑर्डर लगाएँ। आपकी पुष्टि के बिना कुछ नहीं लगता।",
               "principles": ["खरीद या बिक्री, मात्रा और सिंबल लिखें।",
                              "ऑप्शन के लिए लॉट, इंडेक्स, स्ट्राइक और CE या PE लिखें।",
                              "असिस्टेंट प्रस्ताव देता है; पुष्टि आप करते हैं। ऑर्डर पेपर पर ही रहते हैं।"]},
        "examples": [
            {"prompt": "Buy 10 shares of TCS", "tool": "propose_paper_order"},
            {"prompt": "Buy 1 lot NIFTY 26000 CE", "tool": "propose_paper_order"},
            {"prompt": "Show my positions and P&L", "tool": "get_paper_portfolio"},
        ],
        "vague": [{"prompt": "Buy something good", "why": "No quantity and no symbol: there is no order to propose."}],
    },
    {
        "slug": "autopilot", "number": 4, "level": 1, "icon": "bolt",
        "en": {"title": "Autopilot prompts", "badge": "Easiest to start",
               "summary": "Deploy an amount across strong NIFTY 100 stocks in one step.",
               "principles": ["Say the amount: 50,000, 25k or 1 lakh all work.",
                              "Review the basket before you confirm it.",
                              "Autopilot picks from the near-52-week-high screen, equal weight."]},
        "hi": {"title": "ऑटोपायलट प्रॉम्प्ट", "badge": "सबसे आसान शुरुआत",
               "summary": "एक ही कदम में रकम को मज़बूत NIFTY 100 शेयरों में लगाएँ।",
               "principles": ["रकम लिखें: 50,000, 25k या 1 lakh सब चलते हैं।",
                              "पुष्टि से पहले बास्केट देख लें।",
                              "ऑटोपायलट 52-हफ़्ते के ऊँचे स्तर के पास वाली स्क्रीन से बराबर वज़न में चुनता है।"]},
        "examples": [
            {"prompt": "Invest 50,000 in autopilot now", "tool": "propose_autopilot"},
            {"prompt": "What is my autopilot doing?", "tool": "get_autopilot_status"},
            {"prompt": "Invest 1 lakh in autopilot", "tool": "propose_autopilot"},
            {"prompt": "Invest 25k in autopilot", "tool": "propose_autopilot"},
        ],
        "vague": [{"prompt": "Make me money automatically", "why": "No amount: autopilot needs to know how much to deploy."}],
    },
    {
        "slug": "options", "number": 5, "level": 2, "icon": "bars",
        "en": {"title": "Options and OI prompts", "badge": "Beginner friendly",
               "summary": "Support, resistance, PCR and strategies from the live option chain.",
               "principles": ["Name the index: NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY or SENSEX.",
                              "Ask about support, resistance, OI build-up or PCR.",
                              "Option data needs your Upstox account connected."]},
        "hi": {"title": "ऑप्शन और OI प्रॉम्प्ट", "badge": "शुरुआती के लिए",
               "summary": "लाइव ऑप्शन चेन से सपोर्ट, रेज़िस्टेंस, PCR और रणनीतियाँ।",
               "principles": ["इंडेक्स का नाम लिखें: NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY या SENSEX।",
                              "सपोर्ट, रेज़िस्टेंस, OI बिल्ड-अप या PCR पूछें।",
                              "ऑप्शन डेटा के लिए आपका Upstox खाता जुड़ा होना चाहिए।"]},
        "examples": [
            {"prompt": "Where is the support for NIFTY today?", "tool": "get_option_chain_summary"},
            {"prompt": "Which strike has the most OI build-up on BANKNIFTY?", "tool": "get_option_chain_summary"},
            {"prompt": "What is the PCR for NIFTY?", "tool": "get_option_chain_summary"},
            {"prompt": "Suggest an F&O strategy for NIFTY this expiry", "tool": "get_ideas"},
        ],
        "vague": [{"prompt": "Options?", "why": "No index and no question: say which chain and what you want from it."}],
    },
    {
        "slug": "models", "number": 6, "level": 3, "icon": "brain",
        "en": {"title": "Model signal prompts", "badge": "Research",
               "summary": "Ask the trained swing models for rankings, ranges, the market regime and a sized plan.",
               "principles": ["Say 'models' or 'signals' to reach the trained models rather than the rule-based ideas.",
                              "Name a NIFTY 100 stock for its rank, 10-session range and what drove its score.",
                              "Give an amount for a swing plan; it is sized for your risk profile and placed only "
                              "when you confirm.",
                              "Expect ranges, not price targets: a 51% hit rate is what a real market edge looks like."]},
        "hi": {"title": "मॉडल सिग्नल प्रॉम्प्ट", "badge": "रिसर्च",
               "summary": "प्रशिक्षित स्विंग मॉडल से रैंकिंग, रेंज, बाज़ार का रिजीम और एक प्लान पूछें।",
               "principles": ["नियम-आधारित आइडिया के बजाय प्रशिक्षित मॉडल तक पहुँचने के लिए 'models' या 'signals' लिखें।",
                              "NIFTY 100 के किसी शेयर का नाम लिखें: उसकी रैंक, 10 सत्रों की रेंज और स्कोर की वजह मिलेगी।",
                              "स्विंग प्लान के लिए रकम बताएँ; यह आपकी जोखिम प्रोफ़ाइल के हिसाब से बनता है और "
                              "आपकी पुष्टि पर ही लगता है।",
                              "सटीक भाव नहीं, रेंज की उम्मीद रखें: बाज़ार में 51% हिट रेट ही असली बढ़त होती है।"]},
        "examples": [
            {"prompt": "What do the models predict for the next two weeks?", "tool": "get_model_signals"},
            {"prompt": "What do the models say about INFY?", "tool": "get_model_signals"},
            {"prompt": "Is the market risky right now? What's the regime?", "tool": "get_market_regime"},
            {"prompt": "Build me a swing plan with 2 lakh", "tool": "propose_swing_plan"},
            {"prompt": "Give me model picks", "tool": "get_ideas"},
            {"prompt": "How can I invest 50000 in banking, IT and pharma?", "tool": "plan_allocation"},
            {"prompt": "Where should I put 2 lakh for the long term?", "tool": "plan_allocation"},
            {"prompt": "Review my portfolio", "tool": "review_my_portfolio"},
        ],
        "vague": [{"prompt": "Will INFY go up?",
                   "why": "No model can answer yes or no. Ask what the models say about INFY to get its rank and range."}],
    },
]


def book(lang: str = "en") -> dict:
    lang = "hi" if lang == "hi" else "en"
    return {
        "lang": lang, "hero": HERO[lang],
        "chapters": [{"slug": c["slug"], "number": c["number"], "level": c["level"], "icon": c["icon"],
                      **c[lang], "examples": c["examples"], "vague": c["vague"]} for c in CHAPTERS],
    }
