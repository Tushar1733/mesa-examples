# 🧪 Mesa Examples — Health Dashboard
> **Generated:** 2026-03-29 22:46 UTC  
> **Platform:** `win32` · **Python:** `3.14.3`  
> **Mesa version label:** `local` · **Timeout:** 30s

---

## Overall Health

```
  🟡  Health Score : 55%  [███████████░░░░░░░░░]
  ✅  Passed      : 11 / 20
  ❌  Failed      :  9 / 20
  ⏱️  Timeout     :  0 / 20
```

---

## 📊 Summary

| Metric | Count | Share |
|--------|------:|-------|
| ✅ Passed          | **11** | 55.0% |
| ❌ Failed          | **9** | 45.0% |
| ⏱️ Timeout         | **0** | 0.0% |
| ⚠️ Partial (pass/model fail) | **1** | 5.0% |
| 📦 Total examples  | **20** | 100% |

---

## 🔍 Failure Breakdown

| Category | Count | Examples |
|----------|------:|---------|
| Legacy API | 5 | `caching_and_replay`, `charts`, `color_patches`, `hex_snowflake`, `shape_example` |
| ImportError | 3 | `conways_game_of_life_fast`, `emperor_dilemma`, `hex_ant` |
| TypeError | 1 | `termites` |

> **ℹ️ Note — Partial Passes:** The following examples have a green runner status
> but their model unit test failed:
>
> - `bank_reserves`: attempted relative import with no known parent package

---

## 📋 All Examples

| Example | Runner | Model Test | Run Command | Mesa Req | Notes |
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

## ✅ Passing Examples — Model Test Details

### `aco_tsp`
- **Path:** `examples\aco_tsp`
- **Run:** `solara run app.py`
- **Mesa:** `>=3.0`
- **Test:** step() x5 passed  |  num_agents=20, max_steps=1000000, ant_alpha=1.0, ant_beta=5.0, tsp_graph=<aco_tsp.model.TSPGraph object at 0x000002C56AFE3620>

### `boltzmann_wealth_model_network`
- **Path:** `examples\boltzmann_wealth_model_network`
- **Run:** `solara run app.py`
- **Mesa:** `>=3.0`
- **Test:** step() x5 passed  |  n=7, num_nodes=10, rng=None

### `deffuant_weisbuch`
- **Path:** `examples\deffuant_weisbuch`
- **Run:** `solara run app.py`
- **Mesa:** `>=3.0`
- **Test:** step() x5 passed  |  n=100, epsilon=0.2, mu=0.5, rng=None

### `dining_philosophers`
- **Path:** `examples\dining_philosophers`
- **Run:** `solara run app.py`
- **Mesa:** `>=3.0`
- **Test:** step() x5 passed  |  num_philosophers=5, strategy='Naive', hungry_chance=0.1, full_chance=0.2

### `Forest Fire Model`
- **Path:** `examples\forest_fire`
- **Run:** `solara run app.py`
- **Mesa:** `>=3.0`
- **Test:** step() x5 passed  |  width=100, height=100, density=0.65, rng=None

### `hotelling_law`
- **Path:** `examples\hotelling_law`
- **Run:** `solara run app.py`
- **Mesa:** `>=3.0`
- **Test:** step() x5 passed  |  n_stores=20, n_consumers=100, width=50, height=50, mode='default' (+4 more)

### `humanitarian_aid_distribution`
- **Path:** `examples\humanitarian_aid_distribution`
- **Run:** `solara run app.py`
- **Mesa:** `>=3.0`
- **Test:** step() x5 passed  |  num_beneficiaries=30, num_trucks=3, width=20, height=20, rng=None (+1 more)

### `rumor_mill`
- **Path:** `examples\rumor_mill`
- **Run:** `solara run app.py`
- **Mesa:** `>=3.0`
- **Test:** step() x5 passed  |  width=10, height=10, know_rumor_ratio=0.01, rumor_spread_chance=0.5, eight_neightborhood=False (+1 more)

### `virus_antibody`
- **Path:** `examples\virus_antibody`
- **Run:** `solara run app.py`
- **Mesa:** `>=3.0`
- **Test:** step() x5 passed  |  rng=None, initial_antibody=20, initial_viruses=20, width=100, height=100 (+3 more)

### `warehouse`
- **Path:** `examples\warehouse`
- **Run:** `solara run app.py`
- **Mesa:** `>=3.0`
- **Test:** step() x5 passed  |  rng=42

---

## ❌ Failing Examples — Details & Remediation

### `caching_and_replay`
- **Path:** `examples\caching_and_replay`
- **Run command:** `mesa runserver`
- **Mesa:** `>=3.0`
- **Runner notes:** Legacy Mesa API: 'mesa runserver' removed - migrate to 'solara run app.py'
- **Model test:** ✅ passed — step() x5 passed  |  height=20, width=20, homophily=3, radius=1, density=0.8 (+2 more)
- **💡 Remediation:** Migrate `run_command` from `mesa runserver` to `solara run app.py`.

### `charts`
- **Path:** `examples\charts`
- **Run command:** `mesa runserver`
- **Mesa:** `>=2.0`
- **Runner notes:** Legacy Mesa API: 'mesa runserver' removed - migrate to 'solara run app.py'
- **Model test:** ❌ failed — attempted relative import with no known parent package
- **💡 Remediation:** Migrate `run_command` from `mesa runserver` to `solara run app.py`.

### `color_patches`
- **Path:** `examples\color_patches`
- **Run command:** `mesa runserver`
- **Mesa:** `>=3.0`
- **Runner notes:** Legacy Mesa API: 'mesa runserver' removed - migrate to 'solara run app.py'
- **Model test:** ✅ passed — step() x5 passed  |  width=20, height=20
- **💡 Remediation:** Migrate `run_command` from `mesa runserver` to `solara run app.py`.

### `conways_game_of_life_fast`
- **Path:** `examples\conways_game_of_life_fast`
- **Run command:** `solara run app.py`
- **Mesa:** `>=2.3`
- **Runner notes:** ImportError
- **Model test:** ❌ failed — No mesa.Model subclass found in model.py
- **💡 Remediation:** Fix relative imports: ensure the package is installed or run as a module (`python -m <pkg>`).

### `emperor_dilemma`
- **Path:** `examples\emperor_dilemma`
- **Run command:** `solara run app.py`
- **Mesa:** `>=3.0`
- **Runner notes:** ImportError: relative import
- **Model test:** ✅ passed — step() x5 passed  |  width=25, height=25, fraction_true_believers=0.05, k=0.125, homophily=False (+1 more)
- **💡 Remediation:** Fix relative imports: ensure the package is installed or run as a module (`python -m <pkg>`).

### `hex_ant`
- **Path:** `examples\hex_ant`
- **Run command:** `solara run app.py`
- **Mesa:** `>=3.0`
- **Runner notes:** ImportError: relative import
- **Model test:** ❌ failed — attempted relative import with no known parent package
- **💡 Remediation:** Fix relative imports: ensure the package is installed or run as a module (`python -m <pkg>`).

### `hex_snowflake`
- **Path:** `examples\hex_snowflake`
- **Run command:** `mesa runserver`
- **Mesa:** `>=2.0`
- **Runner notes:** Legacy Mesa API: 'mesa runserver' removed - migrate to 'solara run app.py'
- **Model test:** ❌ failed — attempted relative import with no known parent package
- **💡 Remediation:** Migrate `run_command` from `mesa runserver` to `solara run app.py`.

### `shape_example`
- **Path:** `examples\shape_example`
- **Run command:** `mesa runserver`
- **Mesa:** `>=3.0`
- **Runner notes:** Legacy Mesa API: 'mesa runserver' removed - migrate to 'solara run app.py'
- **Model test:** ✅ passed — step() x5 passed  |  num_agents=2, width=20, height=10
- **💡 Remediation:** Migrate `run_command` from `mesa runserver` to `solara run app.py`.

### `termites`
- **Path:** `examples\termites`
- **Run command:** `solara run app.py`
- **Mesa:** `>=3.0`
- **Runner notes:** TypeError
- **Model test:** ❌ failed — HasPropertyLayers.add_property_layer() takes 2 positional arguments but 3 were given
- **💡 Remediation:** Check API signature — a method received too many positional arguments.

---

## ⚙️ Run Configuration

| Parameter | Value |
|-----------|-------|
| Examples directory | `examples` |
| Timeout            | `30s` |
| Skip install       | `False` |
| Mesa version label | `local` |
| Python             | `3.14.3 (tags/v3.14.3:323c59a, Feb  3 2026, 16:04:56) [MSC v.1944 64 bit (AMD64)]` |
| Platform           | `win32` |

---

*Dashboard auto-generated by `generate_dashboard.py`*