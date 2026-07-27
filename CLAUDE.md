# CLAUDE.md

## Project

Build a personal finance web app for personal use.

The app imports CSV statements from multiple banks and credit cards into one database, then helps me understand my spending habits.

My long-term goal is to make better financial decisions and eventually use the data to plan for things like vacations, major purchases, and potentially leaving my full-time job.

## Core Principles

Accuracy is more important than features.

Never guess financial data.

Keep everything local unless I explicitly ask otherwise.

Do not over-engineer the solution.

## Technology

Frontend
- React
- TypeScript
- Vite
- Tailwind

Backend
- FastAPI
- Python
- SQLite
- SQLAlchemy

Charts
- Recharts

AI
- OpenAI API
- Store the API key in `.env`
- Use the OpenAI API to interpret user questions, categorize merchants (when enabled), and explain financial insights.
- Do not use the LLM to calculate totals. All calculations must come from backend code.

## Roadmap

Phase 1
- CSV import (can be found in personalfinanceapp/data)
- Normalize transactions
- Store in SQLite
- Prevent duplicate imports
- Display transactions

Phase 2
- Categories
- Manual category editing
- Merchant cleanup
- Transfers and credit card payments

Phase 3
- Dashboard
- Monthly income vs expenses
- Spending by category
- Top merchants
- Trends
- Six-month summary

Phase 4
- Financial chatbot using OpenAI
- Questions like:
    - Where is my money going?
    - How much did I spend eating out?
    - What categories increased?
    - How much could I save by reducing dining?

Phase 5
- Savings goals
- Vacation planner
- Financial runway
- Scenario analysis

## Development Style

Work in small steps.

After each step:

- explain what changed
- run tests
- summarize results

Stop after each major feature and wait for my approval before continuing. The goal is to build a product I enjoy using every week, not a demo that looks impressive. Favor usefulness over complexity.