# Personal Finance Dashboard

## Purpose

This project is being built to help me better understand my personal finances across multiple bank accounts and credit cards.

I currently download monthly CSV statements from different financial institutions and want one place where all transactions can be combined, cleaned, categorized, and analyzed.

The goal is to make informed financial decisions using my own financial data.

---

## Problems I Want to Solve

I want to answer questions such as:

- How much money came in this month?
- How much money went out this month?
- What are my largest spending categories?
- Am I really spending too much eating out?
- How have my spending habits changed over the last 6 months?
- Which expenses are increasing?
- Where can I realistically reduce spending?
- How much am I saving each month?
- How long could my current lifestyle be supported by my savings?
- How much should I save each month for a vacation or another financial goal?

---

## Vision

The long-term vision is to build an AI-powered personal finance assistant.

The application should allow me to:

- Import transactions from multiple banks and credit cards.
- View a clean and interactive financial dashboard.
- Understand spending trends over time.
- Track savings goals.
- Run "what-if" financial scenarios.
- Ask questions using natural language.
- Receive personalized financial insights based on my own transaction history.

Example questions:

- "Where is my money going?"
- "How much did I spend on dining during the last 6 months?"
- "Which categories increased the most?"
- "How much could I save if I reduced dining by 25%?"
- "Can I afford a $4,000 vacation next summer?"
- "What subscriptions am I paying for?"
- "Show me merchants where I spend the most money."

---

## Design Principles

- Accuracy is more important than features.
- Simplicity is better than unnecessary complexity.
- Build features only when they solve a real problem.
- Financial calculations must always come from application code.
- AI should explain results, identify trends, and answer questions—not invent financial data.
- The application should feel approachable and easy to use, not like accounting software.

---

## Privacy

Financial information is sensitive.

- Keep all transaction data local unless I explicitly decide otherwise.
- Never commit real financial statements or databases to Git.
- Never expose account numbers or sensitive information in logs.
- Use sample data for automated tests.

---

## Current Scope

The first version should work with manually downloaded CSV statements.

The priority is building a trustworthy financial dashboard before considering:

- Direct bank integrations
- Plaid
- Cloud deployment
- Mobile applications
- Multi-user support

---

## Definition of Success

This project is successful when I can confidently answer:

- Where does my money come from?
- Where does my money go?
- How have my spending habits changed over time?
- What expenses could I reduce?
- How much am I saving every month?
- Can I realistically afford a vacation or another major purchase?
- If I leave my current job, what does my financial runway look like?

The goal is not to spend less at all costs.

The goal is to become more intentional with my money so I can spend confidently on the things that matter while reducing spending that doesn't add meaningful value to my life.