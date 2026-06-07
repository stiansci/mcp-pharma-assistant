# clinicaltrials_api_debugger.py (v2 - Corretto errore di battitura)

import httpx
import asyncio
import json

def print_header(title):
    """Funzione helper per stampare titoli chiari."""
    print("\n" + "="*70)
    print(f"--- {title.upper()} ---") # <-- CORRETTO
    print("="*70)

async def run_api_debug():
    base_url = "https://clinicaltrials.gov/api/v2/studies"
    headers = {'User-Agent': 'PharmaKnowledgeDebugger/1.0'}
    
    # --- TEST 1: La query esatta usata dal server ---
    print_header("Test 1: Query usata dal server")
    
    params1 = {
        "query.term": 'AREA[LocationCountry]Italy AND (AREA[InterventionName]"Nirmatrelvir" AND AREA[Condition]"COVID-19")',
        "filter.overallStatus": "RECRUITING",
        "sort": "LastUpdatePostDate:desc",
        "pageSize": 3,
    }
    
    print("URL e parametri inviati:")
    print(f"URL: {base_url}")
    print(f"Params: {json.dumps(params1, indent=2)}")

    async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
        try:
            response1 = await client.get(base_url, params=params1)
            response1.raise_for_status()
            data1 = response1.json()
            
            print(f"\nRISULTATO: {len(data1.get('studies', []))} studi trovati.")
            if data1.get('studies'):
                print("Dettagli del primo studio trovato:")
                first_study = data1['studies'][0]['protocolSection']
                print(f"  NCT ID: {first_study.get('identificationModule', {}).get('nctId')}")
                print(f"  Titolo: {first_study.get('identificationModule', {}).get('briefTitle')}")
                print(f"  Condizioni: {first_study.get('conditionsModule', {}).get('conditions')}")
                print(f"  Interventi: {[i.get('name') for i in first_study.get('armsInterventionsModule', {}).get('interventions', [])]}")
                print("\nDIAGNOSI: Se i dettagli non corrispondono, l'API potrebbe fare un 'matching' ampio.")
            else:
                 print("\nDIAGNOSI: La query non ha prodotto risultati. Questo è corretto se non ci sono studi attivi.")

        except Exception as e:
            print(f"ERRORE durante la chiamata API: {e}")

    # --- TEST 2: Query più restrittiva con 'EXACT' ---
    print_header("Test 2: Query con 'EXACT' per maggiore precisione")

    params2 = {
        "query.term": 'AREA[LocationCountry]Italy AND (AREA[InterventionName]EXACT "Nirmatrelvir" AND AREA[Condition]EXACT "COVID-19")',
        "filter.overallStatus": "RECRUITING",
        "sort": "LastUpdatePostDate:desc",
        "pageSize": 3,
    }
    
    print("URL e parametri inviati:")
    print(f"URL: {base_url}")
    print(f"Params: {json.dumps(params2, indent=2)}")

    async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
        try:
            response2 = await client.get(base_url, params=params2)
            response2.raise_for_status()
            data2 = response2.json()

            print(f"\nRISULTATO: {len(data2.get('studies', []))} studi trovati con 'EXACT'.")
            if data2.get('studies'):
                 print("Dettagli del primo studio:")
                 print(json.dumps(data2['studies'][0], indent=2))
            else:
                print("\nDIAGNOSI: Nessun risultato con ricerca esatta. Questo conferma che lo studio precedente era un 'matching' approssimativo. La nostra logica nel server potrebbe essere migliorata usando 'EXACT' o filtrando i risultati a posteriori.")
        except Exception as e:
            print(f"ERRORE durante la chiamata API: {e}")

if __name__ == "__main__":
    asyncio.run(run_api_debug())