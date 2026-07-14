name: Update Kyoto Sanga ticket data

on:
  workflow_dispatch:

  schedule:
    - cron: "0 7,19 * * *"
      timezone: "Asia/Tokyo"

permissions:
  contents: write

concurrency:
  group: club-ticket-navi-kyoto-data-update
  cancel-in-progress: false

jobs:
  update:
    runs-on: ubuntu-latest
    timeout-minutes: 25

    steps:
      - name: Checkout repository
        uses: actions/checkout@v5

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.12"
          cache: pip

      - name: Install dependencies
        run: python -m pip install -r requirements.txt

      - name: Run parser tests
        run: python -m unittest tests.test_updater -v

      - name: Update public data
        run: python updater.py

      - name: Commit updated data
        shell: bash
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add data/matches.csv data/ticket_news.csv data/metadata.json
          if git diff --cached --quiet; then
            echo "No data changes."
          else
            git commit -m "Update match and ticket data"
            git push
          fi
