import httpx
import asyncio
from typing import List, NamedTuple
from collections import Counter

# --- SCRIPT DI TEST ---

# Parametri che puoi modificare
CONDIZIONE = "Breast Cancer"
PRINCIPIO_ATTIVO = ""
LIMITE_DI_STUDI_DA_TROVARE = 5 

BASE_URL = "https://clinicaltrials.gov/api/v2/studies"
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}

async def find_and_print_italian_studies_final():
    """
    Esegue la ricerca e stampa un riepilogo compatto che include
    solo le città dove il reclutamento è attivo ('RECRUITING').
    """
    print("="*80)
    print(f"Inizio ricerca di studi per '{CONDIZIONE}' con sedi in Italia (Solo Città Recruiting)...")
    print("="*80)

    query_term = f"AREA[LocationCountry]Italy AND ({CONDIZIONE})"
    
    params = {
        "query.term": query_term,
        "filter.overallStatus": "RECRUITING",
        "sort": "LastUpdatePostDate:desc",
        "pageSize": LIMITE_DI_STUDI_DA_TROVARE,
    }
    
    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=30.0) as client:
            response = await client.get(BASE_URL, params=params)
            response.raise_for_status()
            data = response.json()
            studies = data.get('studies', [])
            
            if not studies:
                print(">>> NESSUNO STUDIO TROVATO che corrisponda ai criteri in Italia.")
                return

            print(f">>> Trovati {len(studies)} studi:\n")

            for i, study in enumerate(studies, 1):
                protocol_section = study.get('protocolSection', {})
                id_module = protocol_section.get('identificationModule', {})
                
                nct_id = id_module.get('nctId')
                title = id_module.get('briefTitle') or id_module.get('officialTitle') or "Titolo non disponibile"
                
                contacts_locations_module = protocol_section.get('contactsLocationsModule', {})
                all_locations = contacts_locations_module.get('locations', []) if contacts_locations_module else []
                
                # Raccogliamo dati solo per le sedi italiane
                italian_locations_data = [
                    (loc.get('status', 'UNKNOWN'), loc.get('city', 'N/D'))
                    for loc in all_locations 
                    if loc and loc.get('country') == 'Italy'
                ]
                
                # --- BLOCCO DI STAMPA FINALE ---
                print(f"--- STUDIO #{i} ---")
                print(f"  ID:      {nct_id}")
                print(f"  Titolo:  {title}")
                print(f"  URL:     https://clinicaltrials.gov/study/{nct_id}")

                if not italian_locations_data:
                    print("  Sedi IT: 0")
                else:
                    # 1. Riepilogo degli stati (invariato, è utile)
                    all_statuses = [loc[0] for loc in italian_locations_data]
                    status_counts = Counter(all_statuses)
                    summary_string = ", ".join([f"{count} {status}" for status, count in sorted(status_counts.items())])
                    print(f"  Sedi IT: {len(italian_locations_data)} totali ({summary_string})")

                    # 2. Elenco filtrato delle sole città in stato 'RECRUITING'
                    recruiting_cities = [
                        city for status, city in italian_locations_data if status == 'RECRUITING'
                    ]
                    
                    if not recruiting_cities:
                        print(f"  Città (Recruiting): Nessuna al momento")
                    else:
                        # Rimuovi duplicati e ordina
                        unique_recruiting_cities = sorted(list(set(recruiting_cities)))
                        cities_string = ", ".join(unique_recruiting_cities)
                        print(f"  Città (Recruiting): {cities_string}")
                
                print("-" * 40)

    except httpx.HTTPStatusError as e:
        print(f"!!! ERRORE HTTP: {e.response.status_code} - La richiesta non è valida.")
        print(f"Dettagli: {e.response.text}")
    except Exception as e:
        print(f"!!! ERRORE IMPREVISTO: {e}")

# --- Funzione principale per eseguire il test ---
async def main():
    await find_and_print_italian_studies_final()

if __name__ == "__main__":
    asyncio.run(main())