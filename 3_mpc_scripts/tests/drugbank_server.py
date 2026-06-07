# drugbank_server.py (v2 - con Ricerca Potenziata)

import os
import polars as pl
from fastmcp import FastMCP, Context
from pydantic import BaseModel, Field
from typing import List, Optional

# --- CONFIGURAZIONE E CARICAMENTO DATI ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
PROCESSED_DATA_DIR = os.path.join(PROJECT_ROOT, 'processed_data')

print("Caricamento dati DrugBank in memoria per DrugBankServer...")
try:
    df_drugs = pl.read_parquet(os.path.join(PROCESSED_DATA_DIR, 'drugs.parquet'))
    df_synonyms = pl.read_parquet(os.path.join(PROCESSED_DATA_DIR, 'drug_synonyms.parquet'))
    df_atc = pl.read_parquet(os.path.join(PROCESSED_DATA_DIR, 'drug_atc_codes.parquet'))
    df_interactions = pl.read_parquet(os.path.join(PROCESSED_DATA_DIR, 'drug_interactions.parquet'))
    print("Dati DrugBank caricati con successo.")
except Exception as e:
    print(f"ERRORE CRITICO: Impossibile caricare i file Parquet di DrugBank. {e}")
    df_drugs, df_synonyms, df_atc, df_interactions = None, None, None, None

mcp = FastMCP("DrugBankServer")

# --- MODELLI DATI (PYDANTIC) ---
class DrugInfo(BaseModel):
    drugbank_id: str = Field(description="ID univoco di DrugBank.")
    name: str = Field(description="Nome ufficiale del principio attivo.")

class InteractionInfo(BaseModel):
    source_drug: DrugInfo
    target_drug: DrugInfo
    description: str = Field(description="Descrizione dell'interazione tra i due farmaci.")

# --- LOGICA DI BUSINESS (CON FUNZIONE DI RICERCA CORRETTA) ---

def _find_drug_by_name_or_synonym(name: str) -> Optional[DrugInfo]:
    """
    Cerca un farmaco per nome, controllando prima i nomi principali e poi i sinonimi.
    """
    if df_drugs is None or df_synonyms is None:
        raise ConnectionError("Dati DrugBank non disponibili.")
    
    search_term_lower = name.lower()
    
    # 1. Cerca prima una corrispondenza esatta nel nome principale
    main_record = df_drugs.filter(pl.col('name').str.to_lowercase() == search_term_lower).limit(1)
    if not main_record.is_empty():
        # Trovato subito! Restituisci il risultato.
        return DrugInfo.model_validate(main_record.to_dicts()[0])
        
    # 2. Se non trovato, cerca tra i sinonimi
    synonym_record = df_synonyms.filter(pl.col('synonym').str.to_lowercase() == search_term_lower).limit(1)
    if synonym_record.is_empty():
        # Non trovato neanche qui.
        return None
    
    # 3. Trovato un sinonimo, ora recupera il record principale associato
    drug_id = synonym_record['drugbank_id'][0]
    main_record_from_synonym = df_drugs.filter(pl.col('drugbank_id') == drug_id)
    if main_record_from_synonym.is_empty():
        return None # Incoerenza nei dati: sinonimo trovato ma farmaco principale mancante
    
    return DrugInfo.model_validate(main_record_from_synonym.to_dicts()[0])

def _get_info_by_atc(atc_code: str) -> Optional[DrugInfo]:
    """Trova le informazioni su un farmaco partendo dal suo codice ATC."""
    if df_atc is None or df_drugs is None:
        raise ConnectionError("Dati DrugBank non disponibili.")
    atc_record = df_atc.filter(pl.col('atc_code') == atc_code.upper()).limit(1)
    if atc_record.is_empty():
        return None
    drug_id = atc_record['drugbank_id'][0]
    main_record = df_drugs.filter(pl.col('drugbank_id') == drug_id)
    if main_record.is_empty():
        return None
    return DrugInfo.model_validate(main_record.to_dicts()[0])

def _check_interactions_by_id(drug_ids: List[str]) -> List[InteractionInfo]:
    """Controlla le interazioni tra una lista di farmaci identificati dal loro DrugBank ID."""
    if df_interactions is None or df_drugs is None:
        raise ConnectionError("Dati DrugBank non disponibili.")
    interactions = df_interactions.filter(
        pl.col('source_drug_id').is_in(drug_ids) & pl.col('target_drug_id').is_in(drug_ids)
    )
    if interactions.is_empty():
        return []
    interactions_with_names = interactions.join(
        df_drugs, left_on='source_drug_id', right_on='drugbank_id'
    ).rename({'name': 'source_name'}).join(
        df_drugs, left_on='target_drug_id', right_on='drugbank_id'
    ).rename({'name': 'target_name'})
    response = []
    for row in interactions_with_names.to_dicts():
        response.append(InteractionInfo(
            source_drug=DrugInfo(drugbank_id=row['source_drug_id'], name=row['source_name']),
            target_drug=DrugInfo(drugbank_id=row['target_drug_id'], name=row['target_name']),
            description=row['description']
        ))
    return response

# --- TOOL DEL SERVER MCP (AGGIORNATO) ---

@mcp.tool(description="Cerca un principio attivo su DrugBank usando il suo nome ufficiale, un sinonimo o un nome commerciale (es. 'Nirmatrelvir', 'Aspirin').")
def find_drug_by_name_or_synonym(ctx: Context, name: str) -> Optional[DrugInfo]:
    """
    Cerca un farmaco per nome. Controlla prima i nomi ufficiali e poi la lista dei sinonimi/brand.
    """
    ctx.info(f"Ricerca potenziata in DrugBank per: '{name}'")
    return _find_drug_by_name_or_synonym(name)

@mcp.tool(description="Recupera le informazioni di un principio attivo da DrugBank usando il suo codice ATC.")
def get_info_by_atc(ctx: Context, atc_code: str) -> Optional[DrugInfo]:
    ctx.info(f"Ricerca in DrugBank per codice ATC: '{atc_code}'")
    return _get_info_by_atc(atc_code)

@mcp.tool(description="Controlla le interazioni note tra una lista di farmaci, fornendo i loro DrugBank ID.")
def check_interactions_by_id(ctx: Context, drug_ids: List[str]) -> List[InteractionInfo]:
    ctx.info(f"Controllo interazioni per gli ID: {drug_ids}")
    return _check_interactions_by_id(drug_ids)

# --- LOGICA DI AVVIO ---
def main():
    if df_drugs is None:
        import sys
        print("Impossibile avviare DrugBankServer: errore nel caricamento dei dati.", file=sys.stderr, flush=True)
        sys.exit(1)
    print("Avvio del server MCP 'DrugBankServer' in modalità stdio...")
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()