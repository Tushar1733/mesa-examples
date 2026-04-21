
# CI-Powered Dual Validation System for mesa-examples

Validates every mesa-example against two environments, tracks health status, and surfaces broken examples automatically via GitHub Actions.

> **Note:** The current prototype uses standalone `example.yaml` files per example. Frontmatter YAML integration into `README.md` is planned for the GSoC implementation phase.

---

## How to run locally

```bash
git clone https://github.com/Tushar1733/mesa-examples
cd mesa-examples
pip install -r scripts/requirements.txt

# Validator 1 — latest environment (~2 min)
python scripts/latest_env_validator.py

# Validator 2 — declared environment (~14 min)
python scripts/declared_env_validator.py
```

---

## Demo — Validator 1 (latest environment)

Each example runs through two stages:

```
[ Forest Fire Model ]  (examples/forest_fire)
  [Stage A] Running model unit test ...
    [PASS] step() x5 passed  |  width=100, height=100, density=0.65, rng=None
  Running : solara run app.py
  Step 1  : Starting server process...
  Step 2  : Waiting up to 10s for server to boot (scanning for errors)...
  Step 3  : Boot window complete. Checking for late errors...
  Step 4  : Sending HTTP health-check to http://localhost:8765 ...
  Step 5  : HTTP 200 received. Stopping server...
  [Stage B] Server boot [PASS]

[ termites ]  (examples/termites)
  [Stage A] Running model unit test ...
    [FAIL] HasPropertyLayers.add_property_layer() takes 2 positional arguments but 3 were given
  Step 2  : Error detected in output -> TypeError
  [Stage B] Server boot [FAIL]  TypeError

[ caching_and_replay ]  (examples/caching_and_replay)
  [Stage A] Running model unit test ...
    [PASS] step() x5 passed  |  height=20, width=20, homophily=3, radius=1, density=0.8
  [Stage B] Server boot [FAIL]  Legacy Mesa API: 'mesa runserver' removed - migrate to 'solara run app.py'
```

**Full summary across all 20 examples:**

```
Example Name                    Server    Model Test  Notes
---------------------------------------------------------------
aco_tsp                         PASS      PASS
dining_philosophers             PASS      PASS
virus_antibody                  PASS      PASS
rumor_mill                      PASS      PASS
humanitarian_aid_distribution   PASS      PASS
warehouse                       PASS      PASS
hotelling_law                   PASS      PASS
Forest Fire Model               PASS      PASS
boltzmann_wealth_model_network  PASS      PASS
deffuant_weisbuch               PASS      PASS
bank_reserves                   PASS      FAIL        attempted relative import
emperor_dilemma                 FAIL      PASS        ImportError: relative import
caching_and_replay              FAIL      PASS        Legacy Mesa API: 'mesa runserver' removed
color_patches                   FAIL      PASS        Legacy Mesa API: 'mesa runserver' removed
shape_example                   FAIL      PASS        Legacy Mesa API: 'mesa runserver' removed
charts                          FAIL      FAIL        Legacy Mesa API: 'mesa runserver' removed
hex_ant                         FAIL      FAIL        ImportError: relative import
conways_game_of_life_fast       FAIL      FAIL        ImportError
termites                        FAIL      FAIL        TypeError
hex_snowflake                   FAIL      FAIL        Legacy Mesa API: 'mesa runserver' removed

Server boot (Solara) → PASS: 11  FAIL: 9  TIMEOUT: 0
Model unit test      → PASS: 14  FAIL: 6
```

---

## Demo — Validator 2 (declared environment)

`declared_env_validator.py` creates an **isolated virtualenv per example**, installs only the pinned versions from each example's `requirements.txt`, then runs the same two-stage test. This confirms that declared dependencies are actually sufficient and catches version conflicts invisible to Validator 1.

Takes ~14 minutes across all 20 examples due to per-example environment setup.

---

## JSON report output

Both validators write a structured JSON report committed back to the repo after every CI run. Real output from `example_validation_results(latest-deps).json`:

```json
{
  "generated_at": "2026-04-21T04:27:05.804995+00:00",
  "run": {
    "examples_dir": "examples",
    "timeout_seconds": 30,
    "mesa_version_label": "local",
    "python": "3.12.13",
    "platform": "linux"
  },
  "summary": {
    "total": 20,
    "server_boot": { "passed": 11, "failed": 9, "timeout": 0 },
    "logical_behaviour": { "passed": 14, "failed": 6, "skipped": 0 }
  },
  "examples": [
    {
      "name": "Forest Fire Model",
      "status": "PASS",
      "notes": null,
      "path": "examples/forest_fire",
      "run_command": "solara run app.py",
      "mesa_version": ">=3.0",
      "model_test": {
        "passed": true,
        "notes": "step() x5 passed  |  width=100, height=100, density=0.65, rng=None"
      }
    },
    {
      "name": "termites",
      "status": "FAIL",
      "notes": "TypeError",
      "path": "examples/termites",
      "run_command": "solara run app.py",
      "mesa_version": ">=3.0",
      "model_test": {
        "passed": false,
        "notes": "HasPropertyLayers.add_property_layer() takes 2 positional arguments but 3 were given"
      }
    }
  ]
}
```

This JSON feeds directly into health status labelling, automatic GitHub Issue creation, and the live `example-health.md` dashboard.

---

## How it works

**Two validators** test each example in different environments:

- `latest_env_validator.py` — tests against newest Mesa + dependencies. Catches upstream breakage early.
- `declared_env_validator.py` — creates an isolated venv per example, installs only pinned versions. Confirms declared dependencies are sufficient.

Each validator runs two stages per example:

- **Stage A — model unit test:** initialises the model class and runs `step()` five times, validating internal logic.
- **Stage B — server boot:** spawns the example process, monitors stdout/stderr for known error patterns, then sends an HTTP health-check to confirm the server is actually responsive.

**Scheduled runs** via a weekly cron job (Sunday midnight) catch silent decay from upstream Mesa releases or dependency changes even with no repository activity.

---

## Architecture

```
example.yaml  (metadata per example)
      │
      ▼
┌─────────────────┐     ┌──────────────────────────┐
│  Validator 1    │     │  Validator 2              │
│  latest env     │     │  declared env             │
│  ~2 min         │     │  isolated venv / example  │
│                 │     │  ~14 min                  │
└────────┬────────┘     └────────────┬─────────────┘
         │                           │
         └─────────────┬─────────────┘
                       ▼
                JSON health report
                       │
          ┌────────────┼─────────────┐
          ▼            ▼             ▼
    Health status   GitHub       example-
    lifecycle       Issues       health.md
    labels          (auto)       dashboard
```

---

## Full design

See the [GSoC 2026 proposal discussion](https://github.com/projectmesa/mesa-examples/discussions/417) for complete architecture details including the lifecycle system, issue automation, and CI pipeline design.

# Mesa Examples

## Core Mesa examples
The core Mesa examples are available at the main Mesa repository: https://github.com/mesa/mesa/tree/main/mesa/examples

Those core examples are fully tested, updated and guaranteed to work with the Mesa release that they are included with. They are also included in the Mesa package, so you can access them directly from your Python environment.

## Mesa user examples
This repository contains user examples and showcases that illustrate different features of Mesa. For more information on each model, see its own Readme and documentation.

- Mesa examples that work on the Mesa and Mesa-Geo main development branches are available here on the [`main`](https://github.com/mesa/mesa-examples) branch.
- Mesa examples that work with Mesa 3.x releases are available here on the [`mesa-3.x`](https://github.com/mesa/mesa-examples/tree/mesa-3.x) branch.
- Mesa examples that work with Mesa 2.x releases and Mesa-Geo 0.8.x releases are available here on the [`mesa-2.x`](https://github.com/mesa/mesa-examples/tree/mesa-2.x) branch.

To contribute to this repository, see [CONTRIBUTING.rst](https://github.com/mesa/mesa-examples/blob/main/CONTRIBUTING.rst).

This repo also contains a package that readily lets you import and run some of the examples:
```console
$ # This will install the "mesa_models" package
$ pip install -U -e git+https://github.com/mesa/mesa-examples#egg=mesa-models
```
For Mesa 3.x examples, install:
```console
$ # This will install the "mesa_models" package
$ pip install -U -e git+https://github.com/mesa/mesa-examples@mesa-3.x#egg=mesa-models
```
For Mesa 2.x examples, install:
```console
$ # This will install the "mesa_models" package
$ pip install -U -e git+https://github.com/mesa/mesa-examples@mesa-2.x#egg=mesa-models
```
```python
from mesa_models.boltzmann_wealth_model.model import BoltzmannWealthModel
```
You can see the available models at [setup.cfg](https://github.com/mesa/mesa-examples/blob/main/setup.cfg).
---

## 📋 Health-dashboard for all Examples

| Example | server-run | Model Test | Run Command | Mesa Req | Notes |
|---------|:------:|:----------:|-------------|----------|-------|
| **aco_tsp** | ✅ PASS | ✅ OK | `solara run app.py` | `>=3.0` | — |
| **bank_reserves** | ✅ PASS | ⚠️ FAIL | `solara run app.py` | `>=3.0` | — |
| **boltzmann_wealth_model_network** | ✅ PASS | ✅ OK | `solara run app.py` | `>=3.0` | — |
| **caching_and_replay** | ❌ FAIL | ✅ OK | `mesa runserver` | `>=3.0` | Legacy Mesa API: 'mesa runserver' removed - mig… |
| **charts** | ❌ FAIL | ⚠️ FAIL | `mesa runserver` | `>=2.0` | Legacy Mesa API: 'mesa runserver' removed - mig… |
| **color_patches** | ❌ FAIL | ✅ OK | `mesa runserver` | `>=3.0` | Legacy Mesa API: 'mesa runserver' removed - mig… |
| **conways_game_of_life_fast** | ❌ FAIL | ⚠️ FAIL | `solara run app.py` | `>=2.3` | ImportError |
| **deffuant_weisbuch** | ✅ PASS | ✅ OK | `solara run app.py` | `>=3.0` | — |
| **dining_philosophers** | ✅ PASS | ✅ OK | `solara run app.py` | `>=3.0` | — |
| **emperor_dilemma** | ❌ FAIL | ✅ OK | `solara run app.py` | `>=3.0` | ImportError: relative import |
| **Forest Fire Model** | ✅ PASS | ✅ OK | `solara run app.py` | `>=3.0` | — |
| **hex_ant** | ❌ FAIL | ⚠️ FAIL | `solara run app.py` | `>=3.0` | ImportError: relative import |
| **hex_snowflake** | ❌ FAIL | ⚠️ FAIL | `mesa runserver` | `>=2.0` | Legacy Mesa API: 'mesa runserver' removed - mig… |
| **hotelling_law** | ✅ PASS | ✅ OK | `solara run app.py` | `>=3.0` | — |
| **humanitarian_aid_distribution** | ✅ PASS | ✅ OK | `solara run app.py` | `>=3.0` | — |
| **rumor_mill** | ✅ PASS | ✅ OK | `solara run app.py` | `>=3.0` | — |
| **shape_example** | ❌ FAIL | ✅ OK | `mesa runserver` | `>=3.0` | Legacy Mesa API: 'mesa runserver' removed - mig… |
| **termites** | ❌ FAIL | ⚠️ FAIL | `solara run app.py` | `>=3.0` | TypeError |
| **virus_antibody** | ✅ PASS | ✅ OK | `solara run app.py` | `>=3.0` | — |
| **warehouse** | ✅ PASS | ✅ OK | `solara run app.py` | `>=3.0` | — |

---
Table of Contents
=================

* [Grid Space Examples](#grid-space-examples)
* [Continuous Space Examples](#continuous-space-examples)
* [Network Examples](#network-examples)
* [Visualization Examples](#visualization-examples)
* [GIS Examples](#gis-examples)
* [Other Examples](#other-examples)

## Grid Space Examples

### [Bank Reserves Model](https://github.com/mesa/mesa-examples/blob/main/examples/bank_reserves)

A highly abstracted, simplified model of an economy, with only one type of agent and a single bank representing all banks in an economy.

### [Color Patches Model](https://github.com/mesa/mesa-examples/tree/main/examples/color_patches)

A cellular automaton model where agents opinions are influenced by that of their neighbors. As the model evolves, color patches representing the prevailing opinion in a given area expand, contract, and sometimes disappear.

### [Conway's Game Of "Life" Model (Fast)](https://github.com/mesa/mesa-examples/tree/main/examples/conways_game_of_life_fast)

A very fast performance optimized version of Conway's Game of Life using the Mesa [`PropertyLayer`](https://github.com/mesa/mesa/pull/1898). About 100x as fast as the regular versions, but limited visualisation (for [now](https://github.com/mesa/mesa/issues/2138)).

### [Conway's Game Of "Life" Model on a Hexagonal Grid](https://github.com/mesa/mesa-examples/tree/main/examples/hex_snowflake)

Conway's game of life on a hexagonal grid.

### [Hexagonal Ant Foraging Model](https://github.com/mesa/mesa-examples/tree/main/examples/hex_ant)

A simulation of ant foraging behavior on a hexagonal grid using pheromone trails and property layers.

### [Forest Fire Model](https://github.com/mesa/mesa-examples/tree/main/examples/forest_fire)

Simple cellular automata of a fire spreading through a forest of cells on a grid, based on the NetLogo [Fire](http://ccl.northwestern.edu/netlogo/models/Fire) model.

### [Hotelling's Law Model](https://github.com/mesa/mesa-examples/tree/main/examples/hotelling_law)

This project is an agent-based model implemented using the Mesa framework in Python. It simulates market dynamics based on Hotelling's Law, exploring the behavior of stores in a competitive market environment. Stores adjust their prices and locations if it's increases market share to maximize revenue, providing insights into the effects of competition and customer behavior on market outcomes.

### [Emperor's Dilemma](https://github.com/mesa/mesa-examples/tree/main/examples/emperor_dilemma)

This project simulates how unpopular norms can dominate a society even when the vast majority of individuals privately reject them. It demonstrates the "illusion of consensus" where agents, driven by a fear of appearing disloyal, not only comply with a rule they hate but also aggressively enforce it on their neighbors. This phenomenon creates a "trap" of False Enforcement, where the loudest defenders of a norm are often its secret opponents.
### [Humanitarian Aid Distribution Model](https://github.com/mesa/mesa-examples/tree/main/examples/humanitarian_aid_distribution)

This model simulates a humanitarian aid distribution scenario using a needs-based behavioral architecture. Beneficiaries have dynamic needs (water, food) and trucks distribute aid using a hybrid triage system.
### [Rumor Mill Model](https://github.com/mesa/mesa-examples/tree/main/examples/rumor_mill)

A simple agent-based simulation showing how rumors spread through a population based on the spread chance and initial knowing percentage, implemented with the Mesa framework and adapted from NetLogo [Rumor mill](https://www.netlogoweb.org/launch#https://www.netlogoweb.org/assets/modelslib/Sample%20Models/Social%20Science/Rumor%20Mill.nlogox).


## Continuous Space Examples
_No user examples available yet._


## Network Examples

### [Boltzmann Wealth Model with Network](https://github.com/mesa/mesa-examples/tree/main/examples/boltzmann_wealth_model_network)

This is the same [Boltzmann Wealth](https://github.com/mesa/mesa-examples/tree/main/examples/boltzmann_wealth_model) Model, but with a network grid implementation.

### [Ant System for Traveling Salesman Problem](https://github.com/mesa/mesa-examples/tree/main/examples/aco_tsp)

This is based on Dorigo's Ant System "Swarm Intelligence" algorithm for generating solutions for the Traveling Salesman Problem.

### [Dining Philosophers Model](https://github.com/mesa/mesa-examples/tree/main/examples/dining_philosophers)

A classic synchronization problem demonstrating resource contention, deadlock, and starvation on a network graph.



## Visualization Examples

### [Charts Example](https://github.com/mesa/mesa-examples/tree/main/examples/charts)

A modified version of the [Bank Reserves](https://github.com/mesa/mesa-examples/tree/main/examples/bank_reserves) example made to provide examples of Mesa's charting tools.

### [Shape Example](https://github.com/mesa/mesa-examples/tree/main/examples/shape_example)

Example of grid display and direction showing agents in the form of arrow-head shape.

## GIS Examples

### Vector Data

- [GeoSchelling Model (Polygons)](https://github.com/mesa/mesa-examples/tree/main/gis/geo_schelling)
- [GeoSchelling Model (Points & Polygons)](https://github.com/mesa/mesa-examples/tree/main/gis/geo_schelling_points)
- [GeoSIR Epidemics Model](https://github.com/mesa/mesa-examples/tree/main/gis/geo_sir)
- [Agents and Networks Model](https://github.com/mesa/mesa-examples/tree/main/gis/agents_and_networks)

### Raster Data

- [Rainfall Model](https://github.com/mesa/mesa-examples/tree/main/gis/rainfall)
- [Urban Growth Model](https://github.com/mesa/mesa-examples/tree/main/gis/urban_growth)

### Raster and Vector Data Overlay

- [Population Model](https://github.com/mesa/mesa-examples/tree/main/gis/population)

## Other Examples

### [El Farol Model](https://github.com/mesa/mesa-examples/tree/main/examples/el_farol)

This folder contains an implementation of El Farol restaurant model. Agents (restaurant customers) decide whether to go to the restaurant or not based on their memory and reward from previous trials. Implications from the model have been used to explain how individual decision-making affects overall performance and fluctuation.

### [Schelling Model with Caching and Replay](https://github.com/mesa/mesa-examples/tree/main/examples/caching_and_replay)

This example applies caching on the Mesa [Schelling](https://github.com/mesa/mesa-examples/tree/main/examples/schelling) example. It enables a simulation run to be "cached" or in other words recorded. The recorded simulation run is persisted on the local file system and can be replayed at any later point.
