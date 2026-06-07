# test_external_apis.py (v5 - Stampa URL per debug)

import asyncio
import sys
import os
import httpx # Importiamo httpx per costruire l'URL

# --- IMPOSTAZIONE DEI PERCORSI E IMPORT ---
try:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
    sys.path.append(PROJECT_ROOT)
    from global_knowledge_server import _get_adverse_events, _find_clinical_trials
    print("Importazione delle funzioni API dal server riuscita.")
except ImportError as e:
    print(f"ERRORE di importazione: {e}")
    sys.exit(1)

# --- FUNZIONE DI TEST ASINCRONA ---
async def run_api_tests():
    print("\n" + "="*80)
    print("INIZIO TEST API ESTERNE (con query ad alta probabilità di successo)")
    print("="*80)

    # --- Test 1: API openFDA con "IBUPROFEN" ---
    print("\n[Test 1: Chiamata a openFDA API per 'IBUPROFEN']")
    try:
        principio_attivo_fda = "IBUPROFEN"
        limit_fda = 3
        
        adverse_events = await _get_adverse_events(principio_attivo_fda, limit=limit_fda)
        
        print("\n--- RISULTATO RICEVUTO da openFDA ---")
        if not adverse_events:
            print(" -> NESSUN RISULTATO. Controllare la connessione o possibili blocchi IP.")
        else:
            print(f" -> SUCCESSO. Trovati i {len(adverse_events)} eventi avversi più comuni:")
            for event in adverse_events:
                print(f"    - Termine: {event.term}, Conteggio: {event.count:,}")
    except Exception as e:
        print(f"\n!!!!!! ERRORE IRREVERSIBILE DURANTE IL TEST 1 (openFDA) !!!!!!", e)


    # --- Test 2: API ClinicalTrials.gov con "Breast Cancer" (globale) ---
    print("\n" + "="*80)
    print("[Test 2: Chiamata a ClinicalTrials.gov per 'Breast Cancer' (globale)]")
    try:
        principio_attivo_ct = "" 
        condizione_ct = "Breast Cancer"
        limit_ct = 2

        # --- STAMPA DELLE URL PER DEBUG ---
        base_url = "https://clinicaltrials.gov/api/v2/studies"
        base_params = {
            "query.intr": principio_attivo_ct, "query.cond": condizione_ct,
            "filter.overallStatus": "RECRUITING", "sort": "LastUpdatePostDate:desc"
        }
        params_it = {**base_params, "query.locn": "IT", "pageSize": limit_ct}
        params_total = {**base_params, "pageSize": 0}

        # Usiamo httpx per costruire le URL complete con i parametri codificati correttamente
        url_it = str(httpx.URL(base_url, params=params_it))
        url_total = str(httpx.URL(base_url, params=params_total))
        
        print("\n>>> Copia e incolla queste URL nel tuo browser per verificare <<<")
        print(f"URL per studi in Italia:\n{url_it}")
        print(f"URL per conteggio totale:\n{url_total}")
        print("----------------------------------------------------------------")
        # ------------------------------------

        result = await _find_clinical_trials(principio_attivo_ct, condizione_ct, limit=limit_ct)

        print("\n--- RISULTATO RICEVUTO da ClinicalTrials.gov ---")
        if not result or result.total_recruiting_worldwide == 0:
            print(" -> NESSUN RISULTATO. Verifica le URL qui sopra nel browser.")
        else:
            print(f" -> SUCCESSO. Conteggio totale studi in reclutamento nel mondo: {result.total_recruiting_worldwide}")
            if not result.italian_trials:
                print(" -> NESSUNO STUDIO TROVATO in Italia (risultato possibile).")
            else:
                print(f" -> Trovati {len(result.italian_trials)} studi pertinenti in Italia:")
                for trial in result.italian_trials:
                    print(f"\n    - Titolo: {trial.title}")
                    print(f"      ID: {trial.nct_id}")
                    print(f"      Stato: {trial.status}")
                    print(f"      URL: {trial.url}")
    except Exception as e:
        print(f"\n!!!!!! ERRORE IRREVERSIBILE DURANTE IL TEST 2 (ClinicalTrials.gov) !!!!!!", e)
    
    print("\n" + "="*80)
    print("TEST API COMPLETATI")
    print("="*80)

if __name__ == "__main__":
    asyncio.run(run_api_tests())