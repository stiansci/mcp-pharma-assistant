# MCP Pharma Assistant: An Intelligent MCP Agent for Healthcare

![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)
![Model Context Protocol](https://img.shields.io/badge/Protocol-MCP-purple.svg)
![DuckDB](https://img.shields.io/badge/Database-DuckDB-yellow.svg)
![Polars](https://img.shields.io/badge/Data%20Processing-Polars-lightblue.svg)
![RDKit](https://img.shields.io/badge/Chemoinformatics-RDKit-green.svg)

An open-source, modular AI assistant for the pharmaceutical sector built using the **[Model Context Protocol (MCP)](https://modelcontextprotocol.io/)**. 

This project transforms generic Large Language Models (like Claude) into deterministic, hallucination-free clinical agents by seamlessly connecting them to official healthcare databases, live APIs, and advanced chemoinformatics tools.

---

## The Problem & The Solution

**The Problem:** Doctors and pharmacists need access to highly heterogeneous data (drug availability, reimbursement rules, molecule interactions, clinical trials). Generic LLMs suffer from stochastic hallucinations on specific numerical data and lack real-time access to official government or scientific databases.

**The Solution:** By leveraging the Model Context Protocol, this architecture provides an LLM with external "Tools" to fetch deterministic data. The agent is strictly grounded in official sources, ensuring:
1. **Zero Hallucinations** on prices, dosages, and supply chain shortages.
2. **Real-Time Data** via live APIs for clinical trials and pharmacovigilance.
3. **Advanced Scientific Capabilities** like molecular cross-referencing and dynamic visual rendering.

---

## System Architecture

The ecosystem relies on an Orchestrator (Claude Desktop) connected via `stdio` to **three specialized micro-servers** built with `FastMCP`:

### 1. Italian Pharma Server (Local Sovereignty)
Manages official Italian supply chain data (AIFA - *Agenzia Italiana del Farmaco*).
* **Tech:** `DuckDB`, SQL, `@lru_cache`, `Pydantic`.
* **Features:** Instant lookups for commercial status, hospital shortages (Class H), public pricing, and generic alternatives.
* **Performance:** Complex view queries resolved in `≈23ms`, dropping to `<0.001ms` for cached repeat queries.

### 2. Global Knowledge Server (Big Data & Chemoinformatics)
Acts as the analytical engine for molecular data and drug-drug interactions (DDI) based on DrugBank.
* **Tech:** `Polars`, `RDKit`, `Pillow`.
* **Features:** Resolves entity synonyms, detects interaction conflicts, parses SMILES strings, and generates dynamic 2D molecule structures & LogP (lipophilicity) heatmaps natively in the chat.

### 3. External API Server (Live Knowledge)
An asynchronous gateway to external health authorities.
* **Tech:** `httpx`, `asyncio`.
* **Features:** Non-blocking API calls to **OpenFDA** (for real-world adverse event tracking) and **ClinicalTrials.gov** (to geolocate actively recruiting experimental trials).

---

## Data Engineering & ETL Pipelines

A significant part of this project involves robust ETL pipelines to clean and prepare raw medical data for the MCP servers.

* **Parallel XML Parsing (DrugBank):** Bypassed the Python GIL using `ProcessPoolExecutor` and memory mapping (`mmap`) to process a highly nested 1.5GB XML file. Converted the data into analytical `Parquet` lakes using `Polars` for zero-copy memory efficiency, achieving a 97.5% disk space reduction.
* **Smart CSV Ingestion (AIFA):** Automated encoding detection (`chardet`), regex-based header cleaning, and relational mapping (using AIC codes as universal Foreign Keys) to build a unified in-process `DuckDB` data warehouse.

---

## Installation & Setup

### Prerequisites
* Python 3.10+
* Claude Desktop App (for MCP integration)

### 1. Clone & Install
```bash
git clone https://github.com/yourusername/mcp-pharma-assistant.git
cd mcp-pharma-assistant
pip install -r requirements.txt
```

### 2. Build the Databases (ETL)
Ensure you have the raw CSVs/XMLs in the `0_raw_files` folder, then run:
```bash
# Build the DuckDB AIFA database
python build_aifa_database.py

# Parse DrugBank XML into Parquet files
python process_drugbank_parallel.py
```

### 3. Configure Claude Desktop
Add the FastMCP servers to your `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "ItalianPharmaServer": {
      "command": "python",
      "args": ["/absolute/path/to/italian_pharma_server.py"]
    },
    "GlobalKnowledgeServer": {
      "command": "python",
      "args": ["/absolute/path/to/global_knowledge_server.py"]
    },
    "ExternalAPIServer": {
      "command": "python",
      "args": ["/absolute/path/to/external_api_server.py"]
    }
  }
}
