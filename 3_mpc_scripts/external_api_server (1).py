import os
import httpx
import asyncio
from fastmcp import FastMCP, Context
from pydantic import BaseModel, Field

# Creazione dell'istanza del server MCP con un nome specifico
mcp = FastMCP("ExternalAPIServer")

# --- MODELLI DATI (PYDANTIC) ---
class AdverseEvent(BaseModel):
    term: str = Field(description="L'effetto collaterale (termine MedDRA) segnalato.")
    count: int = Field(description="Il numero di segnalazioni per questo effetto.")

class ClinicalTrialInfo(BaseModel):
    nct_id: str = Field(description="L'identificatore univoco dello studio clinico (NCT ID).")
    title: str = Field(description="Il titolo ufficiale dello studio.")
    status: str = Field(description="Lo stato attuale dello studio (es. Recruiting).")
    url: str = Field(description="Il link alla pagina dettagliata dello studio su ClinicalTrials.gov.")
    recruiting_cities_italy: list[str] = Field(description="Lista delle città in Italia dove lo studio è in fase di reclutamento attivo.")

# --- FUNZIONI PURE E ASINCRONE ---

# Sfruttiamo la libreria httpx per effettuare le chiamate HTTP in modo asincrono
async def _get_adverse_events(principio_attivo: str, limit: int = 5) -> list[AdverseEvent]:
    """
    Interroga l'API openFDA per trovare gli eventi avversi più comuni per un dato principio attivo.

    Args:
        principio_attivo (str): Il nome del principio attivo (deve essere in inglese/USAN).
        limit (int): Il numero massimo di eventi avversi da restituire. Default a 5.

    Returns:
        list[AdverseEvent]: Una lista di oggetti AdverseEvent contenenti il termine dell'evento e il conteggio.
    """
    search_term = principio_attivo.upper()
    
    # Chiediamo all'API openFDA di restituire i 5 eventi avversi più comuni per il principio attivo specificato
    url = f"https://api.fda.gov/drug/event.json?search=patient.drug.activesubstance.activesubstancename:\"{search_term}\"&count=patient.reaction.reactionmeddrapt.exact&limit={limit}"
    
    # Aggiungiamo un header User-Agent per identificare la nostra chiamata
    headers = {'User-Agent': 'Programming For Data Science (Educational Project; c.criscitiello2@studenti.unisa.it)'}    
   
    # Effettuiamo la chiamata HTTP
    # Dopo 15 secondi, se non siamo ancora arrivati a una risposta, la chiamata viene interrotta
    async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
        try:
            # Effettuiamo la chiamata HTTP
            response = await client.get(url)

            # Se la chiamata non ha avuto successo, solleviamo un'eccezione
            response.raise_for_status()

            # Convertiamo la risposta in JSON
            data = response.json()
            
            # Se c'è un errore, lo stampiamo e restituiamo una lista vuota
            if "error" in data:
                print(f"Errore restituito dall'API openFDA: {data['error']['message']}")
                return []
            
            # Convertiamo i risultati in oggetti AdverseEvent
            return [AdverseEvent.model_validate(item) for item in data.get('results', [])]

        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            print(f"Errore di connessione durante la chiamata all'API openFDA: {e}")
            return []

# Uso di | None invece di Optional
async def _find_clinical_trials(principio_attivo: str | None, condizione: str | None, limit: int = 3) -> list[ClinicalTrialInfo]:
    """
    Cerca studi clinici in Italia su ClinicalTrials.gov basati su principio attivo e/o condizione.

    Args:
        principio_attivo (str | None): Il nome dell'intervento o farmaco da cercare.
        condizione (str | None): La condizione medica o patologia oggetto di studio.
        limit (int): Il numero massimo di studi da restituire. Default a 3.

    Returns:
        list[ClinicalTrialInfo]: Una lista di studi clinici trovati che soddisfano i criteri di ricerca e localizzazione (Italia).
    """
    search_parts = []
    if principio_attivo:
        search_parts.append(f"AREA[InterventionName]\"{principio_attivo}\"")
    if condizione:
        search_parts.append(f"AREA[Condition]\"{condizione}\"")
    
    if not search_parts:
        return []
    
    query_expression = f"AREA[LocationCountry]Italy AND ({' AND '.join(search_parts)})"

    # Parametri per la chiamata all'API
    params = {
        "query.term": query_expression,
        "filter.overallStatus": "RECRUITING",
        "sort": "LastUpdatePostDate:desc",
        "pageSize": limit,
    }
    headers = {'User-Agent': 'PharmaKnowledgeBot/1.0 (+http://your-project-url.com)'}
    base_url = "https://clinicaltrials.gov/api/v2/studies"

    async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
        try:
            response = await client.get(base_url, params=params)
            response.raise_for_status()
            data = response.json()
            
            trials = []
            for study in data.get('studies', []):
                protocol = study.get('protocolSection', {})
                id_module = protocol.get('identificationModule', {})
                status_module = protocol.get('statusModule', {})
                nct_id = id_module.get('nctId')
                title = id_module.get('briefTitle') or protocol.get('officialTitle', 'N/A')
                status = status_module.get('overallStatus', 'N/A')
                
                locations = protocol.get('contactsLocationsModule', {}).get('locations', [])
                recruiting_cities = sorted(list(set(
                    loc.get('city') for loc in locations 
                    if loc and loc.get('country') == 'Italy' and loc.get('status') == 'RECRUITING' and loc.get('city')
                )))

                if nct_id:
                    trials.append(ClinicalTrialInfo(
                        nct_id=nct_id, title=title, status=status,
                        url=f"https://clinicaltrials.gov/study/{nct_id}",
                        recruiting_cities_italy=recruiting_cities
                    ))
            return trials
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            print(f"Errore durante la chiamata all'API ClinicalTrials.gov: {e}")
            return []

# --- TOOL DEL SERVER MCP (WRAPPER ASINCRONI) ---

@mcp.tool(description="Cerca su openFDA i 5 eventi avversi più segnalati per un dato principio attivo.")
async def get_adverse_events(ctx: Context, principio_attivo: str) -> list[AdverseEvent]:
    """
    Tool MCP per cercare eventi avversi.
    IMPORTANTE: L'API openFDA utilizza la nomenclatura farmaceutica USA (USAN).
    L'LLM deve utilizzare il principio attivo in inglese (US) prima di chiamare questo tool.
    
    Esempio:
    - Se l'utente chiede "Paracetamolo", il tool deve essere chiamato con "Acetaminophen".

    Args:
        ctx (Context): Il contesto di esecuzione MCP.
        principio_attivo (str): Il principio attivo in inglese (es. 'Acetaminophen').

    Returns:
        list[AdverseEvent]: Lista degli eventi avversi più frequenti segnalati.
    """
    ctx.info(f"Ricerca eventi avversi su openFDA per: '{principio_attivo}'")
    return await _get_adverse_events(principio_attivo, limit=5)

@mcp.tool(description="Cerca studi clinici in fase di reclutamento in Italia, filtrando per principio attivo e/o condizione medica.")
async def find_clinical_trials(ctx: Context, principio_attivo: str | None = None, condizione: str | None = None) -> list[ClinicalTrialInfo]:
    """
    Tool MCP per cercare studi clinici attivi in Italia.

    Args:
        ctx (Context): Il contesto di esecuzione MCP.
        principio_attivo (str | None): (Opzionale) Il principio attivo oggetto dello studio.
        condizione (str | None): (Opzionale) La patologia oggetto dello studio.

    Returns:
        list[ClinicalTrialInfo]: Lista degli studi clinici trovati.

    Raises:
        ValueError: Se non viene specificato né il principio attivo né la condizione.
    """
    if not principio_attivo and not condizione:
        raise ValueError("Errore: specificare almeno un principio attivo o una condizione medica.")
    ctx.info(f"Ricerca studi clinici in Italia per principio attivo '{principio_attivo}' e condizione '{condizione}'")
    return await _find_clinical_trials(principio_attivo, condizione, limit=3)

# --- LOGICA DI AVVIO ---
def main():
    """
    Punto di ingresso dello script. Avvia il server MCP in modalità stdio.
    """
    print("Avvio del server MCP 'ExternalAPIServer' in modalità stdio...")
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()