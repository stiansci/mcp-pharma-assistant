import os
import sys
import polars as pl
from fastmcp import FastMCP, Context
from pydantic import BaseModel, Field
from typing import List, Optional

# --- CONFIGURAZIONE E CARICAMENTO DATI ---
# Utilizziamo percorsi relativi per garantire la portabilità del codice
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
PROCESSED_DATA_DIR = os.path.join(PROJECT_ROOT, '2_drugbank', 'parquet_files')

# Inizializzazione del Server
mcp = FastMCP("GlobalKnowledgeServer")

print("Caricamento dati DrugBank in memoria (Polars)...")
try:
    # Caricamento lazy/eager dei file Parquet. 
    # Polars è estremamente efficiente e mantiene bassi i consumi di memoria.
    if not os.path.exists(PROCESSED_DATA_DIR):
        raise FileNotFoundError(f"Directory dati non trovata: {PROCESSED_DATA_DIR}")

    df_drugs = pl.read_parquet(os.path.join(PROCESSED_DATA_DIR, 'drugs.parquet'))
    df_synonyms = pl.read_parquet(os.path.join(PROCESSED_DATA_DIR, 'synonyms.parquet'))
    df_atc = pl.read_parquet(os.path.join(PROCESSED_DATA_DIR, 'atc_codes.parquet'))
    df_interactions = pl.read_parquet(os.path.join(PROCESSED_DATA_DIR, 'interactions.parquet'))
    
    print(f" -> Dati caricati. Farmaci indicizzati: {df_drugs.height}")
except Exception as e:
    print(f"ERRORE CRITICO: Impossibile caricare i file Parquet di DrugBank. {e}", file=sys.stderr)
    # Impostiamo a None per gestire il fallback nei tool
    df_drugs, df_synonyms, df_atc, df_interactions = None, None, None, None

# --- MODELLI DATI (PYDANTIC) ---

class DrugInfo(BaseModel):
    drugbank_id: str = Field(description="ID univoco DrugBank (es. DB00316)")
    name: str = Field(description="Nome internazionale del farmaco")
    type: str | None = Field(default=None, description="Tipo molecola (es. small molecule, biotech)")
    state: str | None = Field(default=None, description="Stato fisico (es. solid, liquid)")

class InteractionInfo(BaseModel):
    source_drug: DrugInfo
    target_drug: DrugInfo
    description: str = Field(description="Descrizione clinica dell'interazione tra i due farmaci.")

# --- LOGICA DI BUSINESS (FUNZIONI DI RICERCA POLARS) ---

def _find_drug_by_synonym(name: str) -> Optional[DrugInfo]:
    """
    Cerca un farmaco in DrugBank usando un sinonimo o il nome commerciale internazionale.
    Esempio: 'Tylenol' -> Restituisce info su 'Acetaminophen'.
    """
    if df_synonyms is None or df_drugs is None: 
        raise ConnectionError("Database DrugBank non caricato correttamente.")

    # 1. Cerca il DrugID tramite il sinonimo (case insensitive)
    synonym_record = df_synonyms.filter(pl.col('synonym').str.to_lowercase() == name.lower()).limit(1)
    
    drug_id = None
    
    if not synonym_record.is_empty():
        drug_id = synonym_record['drugbank_id'][0]
    else:
        # Fallback: prova a cercare direttamente nel nome del farmaco principale
        drug_record = df_drugs.filter(pl.col('name').str.to_lowercase() == name.lower()).limit(1)
        if not drug_record.is_empty():
            return DrugInfo.model_validate(drug_record.to_dicts()[0])
            
    if not drug_id:
        return None

    # 2. Recupera i dettagli dal DataFrame principale
    main_record = df_drugs.filter(pl.col('drugbank_id') == drug_id)
    
    if main_record.is_empty(): 
        return None
        
    return DrugInfo.model_validate(main_record.to_dicts()[0])

def _get_info_by_atc(atc_code: str) -> Optional[DrugInfo]:
    """
    Identifica il principio attivo internazionale partendo da un codice ATC.
    """
    if df_atc is None or df_drugs is None: 
        raise ConnectionError("Database DrugBank non caricato correttamente.")

    atc_record = df_atc.filter(pl.col('atc_code') == atc_code.upper()).limit(1)
    
    if atc_record.is_empty(): 
        return None
        
    drug_id = atc_record['drugbank_id'][0]
    main_record = df_drugs.filter(pl.col('drugbank_id') == drug_id)
    
    if main_record.is_empty(): 
        return None
        
    return DrugInfo.model_validate(main_record.to_dicts()[0])

def _check_interactions_by_id(drug_ids: List[str]) -> List[InteractionInfo]:
    """
    Verifica le interazioni molecolari note tra una lista di ID DrugBank.
    Esegue un self-join o filtri complessi sul dataset delle interazioni.
    """
    if df_interactions is None or df_drugs is None: 
        raise ConnectionError("Database DrugBank non caricato correttamente.")
    
    if len(drug_ids) < 2:
        return []

    # Filtra le interazioni dove SIA la sorgente CHE il target sono nella lista degli ID forniti
    interactions = df_interactions.filter(
        pl.col('source_drug_id').is_in(drug_ids) & pl.col('target_drug_id').is_in(drug_ids)
    )
    
    if interactions.is_empty(): 
        return []
    
    # Arricchisce i dati (Join) per ottenere i nomi leggibili dei farmaci invece dei soli ID
    # Join per il Source Name
    interactions_enriched = interactions.join(
        df_drugs.select(['drugbank_id', 'name']), 
        left_on='source_drug_id', 
        right_on='drugbank_id'
    ).rename({'name': 'source_name'})
    
    # Join per il Target Name
    interactions_enriched = interactions_enriched.join(
        df_drugs.select(['drugbank_id', 'name']), 
        left_on='target_drug_id', 
        right_on='drugbank_id'
    ).rename({'name': 'target_name'})
    
    response = []
    for row in interactions_enriched.to_dicts():
        response.append(InteractionInfo(
            source_drug=DrugInfo(drugbank_id=row['source_drug_id'], name=row['source_name']),
            target_drug=DrugInfo(drugbank_id=row['target_drug_id'], name=row['target_name']),
            description=row['description']
        ))
        
    return response

# --- TOOL DEL SERVER MCP ---

@mcp.tool(description="Cerca informazioni scientifiche su un farmaco (ID, tipo) usando un sinonimo (es. nome commerciale USA) o il nome molecola.")
def resolve_drug_entity(ctx: Context, name: str) -> Optional[DrugInfo]:
    """
    Risolve il nome di un farmaco per ottenere il suo ID DrugBank univoco.
    Utile come primo passo prima di cercare interazioni.
    """
    ctx.info(f"Risoluzione entità DrugBank per: '{name}'")
    return _find_drug_by_synonym(name)

@mcp.tool(description="Trova il farmaco internazionale associato a un codice ATC.")
def get_drug_by_atc(ctx: Context, atc_code: str) -> Optional[DrugInfo]:
    """
    Permette di passare dal codice di classificazione anatomica (ATC) al record del farmaco.
    """
    ctx.info(f"Ricerca in DrugBank per codice ATC: '{atc_code}'")
    return _get_info_by_atc(atc_code)

@mcp.tool(description="Verifica le interazioni note tra una lista di ID DrugBank.")
def check_drug_interactions(ctx: Context, drug_ids: List[str]) -> List[InteractionInfo]:
    """
    Analizza potenziali interazioni pericolose. Richiede gli ID DrugBank (es. DB00316),
    che possono essere ottenuti tramite 'resolve_drug_entity'.
    """
    ctx.info(f"Analisi interazioni per gli ID: {drug_ids}")
    return _check_interactions_by_id(drug_ids)

# --- AVVIO SERVER ---

def main():
    if df_drugs is None:
        print("Impossibile avviare il server: errore critico caricamento dati (vedi log sopra).", file=sys.stderr)
        sys.exit(1)
        
    print("Avvio del server MCP 'GlobalKnowledgeServer' (DrugBank) in modalità stdio...")
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()