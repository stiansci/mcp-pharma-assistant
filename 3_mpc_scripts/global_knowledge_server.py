import os
import sys
import polars as pl
from fastmcp import FastMCP, Context, Image 
from pydantic import BaseModel, Field
from typing import List, Optional

# RDKit e Pillow per la visualizzazione molecolare
from rdkit import Chem  # Modulo principale per la chimica computazionale e manipolazione molecole
from rdkit.Chem import Draw  # Modulo per il rendering e disegno 2D delle strutture chimiche
from rdkit.Chem.Draw import SimilarityMaps  # Strumenti per creare mappe di similarità e heatmap molecolari
from rdkit.Chem.Draw import MolDraw2DCairo  # Backend grafico Cairo per generare immagini PNG di alta qualità
from PIL import Image as PILImage  # Libreria Pillow per gestione immagini (alias per evitare conflitti con Image di FastMCP)


# CONFIGURAZIONE E CARICAMENTO DATI 
# Utilizziamo percorsi relativi per garantire la portabilità del codice
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
PROCESSED_DATA_DIR = os.path.join(PROJECT_ROOT, '2_drugbank', 'parquet_files')
VISUALIZATION_DIR = os.path.join(PROJECT_ROOT, 'smiles')

# Inizializzazione del Server
mcp = FastMCP("GlobalKnowledgeServer")

print("Caricamento dati DrugBank in memoria con Polars...")
try:
    # Caricamento lazy/eager dei file Parquet. 
    if not os.path.exists(PROCESSED_DATA_DIR):
        raise FileNotFoundError(f"Directory dati non trovata: {PROCESSED_DATA_DIR}")

    df_drugs = pl.read_parquet(os.path.join(PROCESSED_DATA_DIR, 'drugs.parquet'))
    df_synonyms = pl.read_parquet(os.path.join(PROCESSED_DATA_DIR, 'synonyms.parquet'))
    df_atc = pl.read_parquet(os.path.join(PROCESSED_DATA_DIR, 'atc_codes.parquet'))
    df_interactions = pl.read_parquet(os.path.join(PROCESSED_DATA_DIR, 'interactions.parquet'))
    
    # height è l'equivalente di len() per Polars
    print(f" -> Dati caricati. Farmaci indicizzati: {df_drugs.height}")
except Exception as e:
    print(f"ERRORE: Impossibile caricare i file Parquet di DrugBank. {e}", file=sys.stderr)

    # Impostiamo a None per gestire il fallback nei tool
    df_drugs, df_synonyms, df_atc, df_interactions = None, None, None, None

# MODELLI DATI (PYDANTIC)

class DrugInfo(BaseModel):
    """
    Modello dati per le informazioni sul farmaco.
    """
    drugbank_id: str = Field(description="ID univoco DrugBank (es. DB00316)")
    name: str = Field(description="Nome internazionale del farmaco")
    type: str | None = Field(default=None, description="Tipo molecola (es. small molecule, biotech)")
    state: str | None = Field(default=None, description="Stato fisico (es. solid, liquid)")

class InteractionInfo(BaseModel):
    """
    Modello dati per descrivere un'interazione tra due farmaci.
    """
    source_drug: DrugInfo
    target_drug: DrugInfo
    description: str = Field(description="Descrizione clinica dell'interazione tra i due farmaci.")

# FUNZIONI DI RICERCA POLARS

def _find_drug_by_synonym(name: str) -> Optional[DrugInfo]:
    """
    Cerca un farmaco in DrugBank usando un sinonimo o il nome commerciale internazionale.
    Esempio: 'Tylenol' -> Restituisce info su 'Acetaminophen'.

    Args:
        name (str): Il nome o sinonimo da cercare.

    Returns:
        Optional[DrugInfo]: Oggetto con i dati del farmaco o None se non trovato.
    """
    if df_synonyms is None or df_drugs is None: 
        raise ConnectionError("Database DrugBank non caricato correttamente.")

    # 1. Cerca il DrugID tramite il sinonimo (case insensitive)

    # filter() è il metodo per filtrare i le righe in Polars
    # pl.col() è il metodo per accedere alle colonne in Polars
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

    Args:
        atc_code (str): Codice ATC (es. A02BC).

    Returns:
        Optional[DrugInfo]: Oggetto farmaco corrispondente o None.
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

    Args:
        drug_ids (List[str]): Lista di ID univoci (es. ['DB001', 'DB002']).

    Returns:
        List[InteractionInfo]: Lista delle interazioni trovate tra le coppie.
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

    Args:
        ctx (Context): Contesto FastMCP.
        name (str): Nome o sinonimo del farmaco.

    Returns:
        Optional[DrugInfo]: Info del farmaco o None.
    """
    ctx.info(f"Risoluzione entità DrugBank per: '{name}'")
    return _find_drug_by_synonym(name)

@mcp.tool(description="Trova il farmaco internazionale associato a un codice ATC.")
def get_drug_by_atc(ctx: Context, atc_code: str) -> Optional[DrugInfo]:
    """
    Permette di passare dal codice di classificazione anatomica (ATC) al record del farmaco.

    Args:
        ctx (Context): Contesto FastMCP.
        atc_code (str): Codice ATC.

    Returns:
        Optional[DrugInfo]: Info del farmaco o None.
    """
    ctx.info(f"Ricerca in DrugBank per codice ATC: '{atc_code}'")
    return _get_info_by_atc(atc_code)

@mcp.tool(description="Verifica le interazioni note tra una lista di ID DrugBank.")
def check_drug_interactions(ctx: Context, drug_ids: List[str]) -> List[InteractionInfo]:
    """
    Analizza potenziali interazioni pericolose. Richiede gli ID DrugBank (es. DB00316),
    che possono essere ottenuti tramite 'resolve_drug_entity'.

    Args:
        ctx (Context): Contesto FastMCP.
        drug_ids (List[str]): Lista ID farmaci.

    Returns:
        List[InteractionInfo]: Lista interazioni rilevate.
    """
    ctx.info(f"Analisi interazioni per gli ID: {drug_ids}")
    return _check_interactions_by_id(drug_ids)

@mcp.tool(description="Genera visualizzazioni grafiche avanzate della molecola (Struttura 2D e Heatmap di Solubilità LogP).")
def visualize_molecule_properties(ctx: Context, drug_name: str) -> Image:
    """
    Estrae il codice SMILES, calcola i contributi atomici alla lipofilia (LogP)
    e genera un pannello grafico contenente la struttura chimica e la heatmap di solubilità.
    """
    ctx.info(f"Avvio generazione visualizzazioni molecolari per: '{drug_name}'")

    if df_drugs is None:
        return "Errore: Database non caricato."

    # 1. Recupero SMILES
    try:
        result = df_drugs.filter(
            pl.col('name').str.to_lowercase() == drug_name.lower()
        ).select("smiles").head(1)
        
        if result.is_empty() or not result['smiles'][0]:
            return f"Nessun dato molecolare trovato per '{drug_name}'."
        
        smiles_code = result['smiles'][0]
        mol = Chem.MolFromSmiles(smiles_code)
        if not mol:
            return "SMILES non valido."

        # Setup cartella
        if not os.path.exists(VISUALIZATION_DIR):
            os.makedirs(VISUALIZATION_DIR)

        # Percorsi temporanei
        path_struct = os.path.join(VISUALIZATION_DIR, "temp_struct.png")
        path_heat = os.path.join(VISUALIZATION_DIR, "temp_heat.png")
        path_combined = os.path.join(VISUALIZATION_DIR, "final_panel.png")

        # 2. Genera Immagine 1: Struttura
        img_struct = Draw.MolToImage(mol, size=(400, 400))
        img_struct.save(path_struct)

        # 3. Genera Immagine 2: Heatmap (LogP) con motore Cairo
        contribs = Chem.rdMolDescriptors._CalcCrippenContribs(mol)
        weights = [x[0] for x in contribs]
        
        drawer = MolDraw2DCairo(400, 400)
        SimilarityMaps.GetSimilarityMapFromWeights(mol, weights, draw2d=drawer)
        drawer.FinishDrawing()
        with open(path_heat, "wb") as f:
            f.write(drawer.GetDrawingText())

        # 4. TRUCCO VISIVO: Uniamo le due immagini in una sola (Side-by-Side)
        # Questo garantisce che Claude mostri tutto in un unico blocco visivo
        image1 = PILImage.open(path_struct)
        image2 = PILImage.open(path_heat)
        
        # Crea una tela larga il doppio (400+400) x 400
        combined_img = PILImage.new('RGB', (800, 400))
        combined_img.paste(image1, (0, 0))
        combined_img.paste(image2, (400, 0))
        
        # Salva il pannello finale
        combined_img.save(path_combined)

        ctx.info(f"Pannello grafico generato in: {path_combined}")

        # 5. RETURN FONDAMENTALE
        # Restituiamo un oggetto Image di FastMCP. 
        # La libreria leggerà i byte dal disco e li invierà a Claude per il rendering.
        return Image(path=path_combined)

    except Exception as e:
        ctx.error(f"Errore generazione: {e}")
        return f"Errore tecnico nella generazione grafica: {str(e)}"

# --- AVVIO SERVER ---

def main():
    if df_drugs is None:
        print("Impossibile avviare il server: errore critico caricamento dati (vedi log sopra).", file=sys.stderr)
        sys.exit(1)
        
    print("Avvio del server MCP 'GlobalKnowledgeServer' (DrugBank) in modalità stdio...")
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()