import os
import sys
import duckdb
from functools import lru_cache
from fastmcp import FastMCP, Context
from pydantic import BaseModel, Field, ConfigDict

# 1. CONFIGURAZIONE E INIZIALIZZAZIONE AMBIENTE

# Calcoliamo i percorsi assoluti per rendere lo script robusto
SCRIPT_DIR: str = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT: str = os.path.dirname(SCRIPT_DIR) # Sale di un livello
AIFA_DB_PATH: str = os.path.join(PROJECT_ROOT, '1_aifa', 'aifa.db')

con = None
try:
    if not os.path.exists(AIFA_DB_PATH):
        raise FileNotFoundError(f"Database non trovato nel percorso: {AIFA_DB_PATH}")
    
    con = duckdb.connect(database=AIFA_DB_PATH, read_only=True)
    print(f"Connessione a '{AIFA_DB_PATH}' stabilita con successo.")
except Exception as e:
    print(f"ERRORE CRITICO: Impossibile connettersi al DB. {e}", file=sys.stderr)

mcp = FastMCP("ItalianPharmaServer")

# 2. MODELLI DATI (PYDANTIC)

class PrincipioAttivo(BaseModel):
    """Rappresenta un singolo componente attivo del farmaco."""
    principio_attivo: str | None = None
    quantita: float | None = None
    unita_misura: str | None = None

class FarmacoEquivalente(BaseModel):
    """Rappresenta un risultato della ricerca di farmaci generici."""
    codice_aic: int
    denominazione_farmaco: str
    azienda: str
    prezzo_pubblico: float | None = None

class DettaglioConfezione(BaseModel):
    """
    Rappresenta una singola scatola/confezione (identificata da AIC).
    Contiene informazioni cruciali sullo stato di carenza.
    """
    model_config = ConfigDict(populate_by_name=True)
    
    codice_aic: int
    denominazione_completa: str = Field(alias='denominazione')
    classe_rimborsabilita: str | None = None
    is_carente: bool
    data_inizio_carenza: str | None = None
    motivazioni_carenza: str | None = None

class StatoCommercialeFarmaco(BaseModel):
    """
    Oggetto aggregato che riassume la situazione di un farmaco.
    """
    nome_ricercato: str
    stato_generale: str = Field(description="Riassunto testuale dello stato: 'Disponibile', 'Parzialmente Carente', ecc.")
    confezioni_attive: list[DettaglioConfezione] = Field(description="Lista delle confezioni attualmente acquistabili.")
    confezioni_carenti_o_ritirate: list[DettaglioConfezione] = Field(description="Lista delle confezioni che non si trovano.")
    principi_attivi_rilevati: list[str] = Field(description="Lista dei principi attivi (es. 'Paracetamolo') trovati analizzando le confezioni.")


# 3. FUNZIONI INTERNE

@lru_cache(maxsize=512)
def _get_active_ingredients_by_aic(codice_aic: int) -> list[PrincipioAttivo]:
    """
    Recupera i principi attivi per un dato codice AIC interrogando il database.
    Utilizza un sistema di caching LRU per ottimizzare le richieste frequenti.

    Args:
        codice_aic (int): Il codice identificativo univoco della confezione (AIC).

    Returns:
        list[PrincipioAttivo]: Una lista di oggetti PrincipioAttivo associati a quell'AIC.
    """
    if not con: raise ConnectionError("DB non connesso.")
    
    query = "SELECT principio_attivo, quantita, unita_misura FROM principi_attivi WHERE codice_aic = ?;"

    # [codice_aic] perché execute si aspetta una sequenza di parametri
    # fetchdf() restituisce un DataFrame con i risultati
    results = con.execute(query, [codice_aic]).fetchdf()
    
    return [PrincipioAttivo.model_validate(row) for row in results.to_dict('records')]

def _analizza_stato_farmaco_per_nome(nome_commerciale: str) -> StatoCommercialeFarmaco | None:
    """
    Cerca un farmaco per nome e aggrega lo stato di tutte le sue confezioni (attive vs carenti).
    Estrae inoltre i principi attivi comuni trovati.

    Args:
        nome_commerciale (str): Il nome (o parte del nome) del farmaco da cercare (es. 'Tachipirina').

    Returns:
        StatoCommercialeFarmaco | None: Un oggetto riassuntivo con le liste di confezioni e lo stato generale,
        oppure None se nessun farmaco viene trovato.
    """
    if not con: raise ConnectionError("DB non connesso.")
    
    # 1. Ricerca ampia
    query = "SELECT * FROM farmaci_completi WHERE lower(denominazione) LIKE ?;"
    results_df = con.execute(query, [f"%{nome_commerciale.lower()}%"]).fetchdf()
    
    if results_df.empty:
        return None
    
    attive: list[DettaglioConfezione] = []
    carenti: list[DettaglioConfezione] = []
    set_principi: set[str] = set()

    # 2. Iterazione e classificazione
    for row_dict in results_df.to_dict('records'):
        principi = _get_active_ingredients_by_aic(row_dict['codice_aic'])
        for pa in principi:
            if pa.principio_attivo and pa.principio_attivo.lower() != 'n.d.':
                set_principi.add(pa.principio_attivo)

        confezione = DettaglioConfezione.model_validate(row_dict)
        
        if confezione.is_carente:
            carenti.append(confezione)
        else:
            attive.append(confezione)

    # 3. Calcolo stato sintetico
    if not attive and carenti:
        descrizione_stato = "Ritirato / Non Disponibile"
    elif attive and carenti:
        descrizione_stato = "Parzialmente Carente (alcune confezioni disponibili, altre no)"
    elif attive and not carenti:
        descrizione_stato = "Disponibile"
    else:
        descrizione_stato = "Stato Indeterminato"
        
    return StatoCommercialeFarmaco(
        nome_ricercato=nome_commerciale,
        stato_generale=descrizione_stato,
        confezioni_attive=attive,
        confezioni_carenti_o_ritirate=carenti,
        principi_attivi_rilevati=sorted(list(set_principi))
    )

def _cerca_equivalenti_db(principio_attivo: str) -> list[FarmacoEquivalente]:
    """
    Esegue una query diretta al DB per trovare i farmaci generici basandosi sul principio attivo.
    I risultati sono ordinati per prezzo pubblico crescente.

    Args:
        principio_attivo (str): Il nome del principio attivo da cercare.

    Returns:
        list[FarmacoEquivalente]: Lista dei farmaci trovati, ordinati dal più economico.
    """
    if not con: raise ConnectionError("DB non connesso.")

    # NULLS LAST perché vogliamo posizionare i nulli in fondo
    query = """
        SELECT codice_aic, farmaco as denominazione_farmaco, ditta as azienda, prezzo_riferimento_ssn as prezzo_pubblico 
        FROM farmaci_equivalenti 
        WHERE lower(principio_attivo) LIKE ? 
        ORDER BY prezzo_pubblico ASC NULLS LAST;
    """
    results = con.execute(query, [f"%{principio_attivo.lower()}%"]).fetchdf()
    
    if results.empty: return []
    return [FarmacoEquivalente.model_validate(row) for row in results.to_dict('records')]


# ==========================================
# 4. TOOL DEL SERVER MCP (Interfaccia Pubblica)
# ==========================================

@mcp.tool(description="Fornisce un quadro completo dello stato commerciale di un farmaco in Italia (cercando per nome).")
def get_drug_commercial_status(ctx: Context, nome_commerciale: str) -> StatoCommercialeFarmaco | None:
    """
    Analizza la disponibilità di un farmaco dato il suo nome commerciale.
    Distingue tra confezioni attive e carenti per fornire un quadro chiaro all'utente.

    Args:
        ctx (Context): Il contesto di esecuzione MCP (usato per il logging).
        nome_commerciale (str): Il nome del farmaco da analizzare (es. 'Oki').

    Returns:
        StatoCommercialeFarmaco | None: L'oggetto contenente lo stato del farmaco o None se non trovato.
    """
    ctx.info(f"Inizio analisi stato commerciale per: '{nome_commerciale}'")
    
    stato = _analizza_stato_farmaco_per_nome(nome_commerciale)
    
    if stato:
        ctx.info(f"Analisi completata. Stato: {stato.stato_generale}. "
                 f"Attive: {len(stato.confezioni_attive)}, Carenti: {len(stato.confezioni_carenti_o_ritirate)}.")
    else:
        ctx.info(f"Nessun farmaco trovato nel DB con il nome '{nome_commerciale}'.")
        
    return stato

@mcp.tool(description="Cerca farmaci generici/equivalenti. Accetta sia un principio attivo che un nome commerciale.")
def find_generics(ctx: Context, query_ricerca: str) -> list[FarmacoEquivalente]:
    """
    Trova farmaci equivalenti ordinati per prezzo. Include una logica "intelligente"
    che tenta di estrarre il principio attivo se l'input sembra essere un nome commerciale.

    Args:
        ctx (Context): Il contesto di esecuzione MCP.
        query_ricerca (str): Può essere un principio attivo (es. 'Ibuprofene') o un nome commerciale (es. 'Brufen').

    Returns:
        list[FarmacoEquivalente]: Lista dei farmaci equivalenti trovati.
    """
    ctx.info(f"Richiesta ricerca equivalenti per: '{query_ricerca}'")
    
    # 1. Strategia "Smart": L'utente ha inserito "Oki" (nome) o "Ketoprofene" (principio)?
    stato_farmaco = _analizza_stato_farmaco_per_nome(query_ricerca)
    
    principio_da_cercare = query_ricerca # Default: assumiamo sia già un principio attivo

    if stato_farmaco and stato_farmaco.principi_attivi_rilevati:
        principio_rilevato = stato_farmaco.principi_attivi_rilevati[0]
        ctx.info(f"Input '{query_ricerca}' interpretato come nome commerciale. "
                 f"Effettuo ricerca generici per principio attivo: '{principio_rilevato}'")
        principio_da_cercare = principio_rilevato
    
    # 2. Eseguiamo la ricerca effettiva
    return _cerca_equivalenti_db(principio_da_cercare)


@mcp.tool(description="Ottiene la lista dettagliata dei principi attivi per un codice AIC specifico.")
def get_active_ingredients_by_aic(ctx: Context, codice_aic: int) -> list[PrincipioAttivo]:
    """
    Recupera la composizione esatta (principi attivi, quantità) di una specifica confezione.

    Args:
        ctx (Context): Il contesto di esecuzione MCP.
        codice_aic (int): Il codice AIC univoco della confezione.

    Returns:
        list[PrincipioAttivo]: Lista dei componenti attivi della confezione.
    """
    ctx.info(f"Recupero principi attivi per AIC: {codice_aic}")
    return _get_active_ingredients_by_aic(codice_aic)

# ==========================================
# 5. LOGICA DI AVVIO (Main)
# ==========================================

def main():
    """
    Punto di ingresso dello script.
    Verifica la connessione al database e avvia il server MCP in modalità stdio.
    """
    if not con:
        print("Impossibile avviare il server: errore connessione DB.", file=sys.stderr)
        sys.exit(1)
    
    print("Avvio del server MCP 'ItalianPharmaServer' in modalità stdio...")
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()