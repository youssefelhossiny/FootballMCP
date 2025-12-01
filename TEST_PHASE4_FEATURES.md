# Phase 4 Feature Testing Guide

Test all FBRef defensive/progressive/creation stats integration across tools.

---

## 1. Basic Data Verification

### Test Understat + FBRef Data Loading
```
Show me Salah's full stats
```
**Expected:** Should show xG, xA, npxG AND defensive stats (tackles, interceptions, etc.)

### Test Defensive Stats Display
```
Show me Saliba's defensive stats
```
**Expected:** Should show tackles, interceptions, blocks, clearances, def_contributions_per_90, and defensive contribution probability

---

## 2. Top Performers - New Metrics

### Defensive Contributions (NEW)
```
Top 10 defenders by defensive contributions per 90
```
**Expected:** Ranked list of defenders by def_contributions_per_90

### Shot-Creating Actions (NEW)
```
Top 10 midfielders by SCA per 90
```
**Expected:** Ranked list of midfielders by sca_per_90

### Goal-Creating Actions (NEW)
```
Top 10 players by GCA per 90
```
**Expected:** Ranked list by gca_per_90

### Progressive Passes (NEW)
```
Top 10 midfielders by progressive passes per 90
```
**Expected:** Ranked list by progressive_passes_per_90

### Compare with xG metrics
```
Top 10 forwards by xG per 90
```
**Expected:** Should still work as before

---

## 3. Player Details - Full Integration

### Forward with xG focus
```
Get detailed stats for Haaland
```
**Expected:**
- FPL stats (form, points, price)
- Understat: xG, xA, npxG, xGChain, xGBuildup
- FBRef: Some defensive stats (lower for forwards)
- Prediction with all 58 features

### Defender with defensive focus
```
Get detailed stats for Van Dijk
```
**Expected:**
- High defensive contributions
- def_contribution_prob (probability of 2pt bonus)
- expected_def_points
- Lower xG/xA (as expected for defender)

### Midfielder with balanced stats
```
Get detailed stats for Saka
```
**Expected:**
- Good xG/xA numbers
- Decent defensive contributions
- High SCA/GCA (creative midfielder)
- Progressive passes/carries

---

## 4. Transfer Evaluation - FBRef Comparison

### Defender vs Defender
```
Evaluate transfer: Gabriel out, Saliba in
```
**Expected:**
- Standard comparison (price, form, points)
- xG comparison
- NEW: Defensive stats comparison (def contributions/90)
- NEW: Defensive contribution probability comparison
- NEW: Creation stats comparison (SCA/GCA)

### Midfielder vs Midfielder
```
Evaluate transfer: Fernandes out, Saka in
```
**Expected:**
- All comparisons including defensive and creation stats

### Forward vs Forward
```
Evaluate transfer: Watkins out, Isak in
```
**Expected:**
- Focus on xG comparison
- Lower but still present defensive stats

---

## 5. Squad Optimization - 58 Features

### Full Squad Build
```
Build optimal squad with 100m budget
```
**Expected:**
- Uses all 58 features for predictions
- Defenders selected should have good def_contributions_per_90
- Midfielders should balance xG/xA with progressive stats

### Position-Specific Optimization
```
Best 5 defenders under 6.0m
```
**Expected:**
- Should factor in defensive contribution potential
- Higher def_contributions_per_90 = better ranking

---

## 6. Transfer Suggestions - Defensive Aware

### General Suggestions
```
Suggest transfers for my team
```
**Expected:**
- Recommendations consider defensive stats for DEF/MID
- Mentions defensive contribution potential where relevant

### Position-Specific
```
Suggest defender transfers under 5.5m
```
**Expected:**
- Should prioritize high def_contributions_per_90
- Mentions probability of earning 2pt defensive bonus

---

## 7. Captain Suggestions - Enhanced

```
Suggest captain for GW15
```
**Expected:**
- Still prioritizes high xG forwards
- May mention defenders with high defensive contribution potential
- Uses fixture difficulty + form + xG + defensive potential

---

## 8. All Players Listing - Defensive Info

### Defenders with Def/90
```
Show all Arsenal defenders
```
**Expected:**
- Each defender should show "Def/90: X.X" in listing
- xG/xA info still present

### Compare positions
```
Show all Liverpool players
```
**Expected:**
- Defenders: Show Def/90
- Forwards/Mids: Show xG/xA
- All positions display correctly

---

## 9. Verification Queries

### Feature Count Check
```
How many features does the model use?
```
**Expected:** 58 features (17 FPL + 20 Understat + 21 FBRef)

### Data Source Check
```
What data sources are integrated?
```
**Expected:** FPL API, Understat (xG/xA), FBRef (defensive/progressive)

---

## 10. Edge Cases

### Player without FBRef match
```
Get stats for a newly promoted team player
```
**Expected:** Should use position-based defaults, not crash

### Player without Understat match
```
Get stats for a reserve goalkeeper
```
**Expected:** Should show FPL stats with defaults for missing data

---

## Quick Test Sequence

Run these in order for comprehensive testing:

1. `Top 10 defenders by defensive contributions per 90`
2. `Show me Van Dijk's full stats`
3. `Evaluate transfer: Gabriel out, Saliba in`
4. `Top 10 midfielders by SCA per 90`
5. `Build optimal squad with 100m budget`
6. `Show all Manchester City players`

---

## Expected Metrics in Output

### For Defenders
| Metric | Description |
|--------|-------------|
| def_contributions_per_90 | Tackles + Int + Blocks + Clearances per 90 |
| def_contribution_prob | Probability of 2pt bonus (needs 10 actions) |
| expected_def_points | Expected defensive points per match |

### For Midfielders
| Metric | Description |
|--------|-------------|
| progressive_passes_per_90 | Forward passes per 90 |
| sca_per_90 | Shot-creating actions per 90 |
| gca_per_90 | Goal-creating actions per 90 |

### For All Players
| Metric | Description |
|--------|-------------|
| xG_per_90 | Expected goals per 90 |
| xA_per_90 | Expected assists per 90 |
| npxG_per_90 | Non-penalty xG per 90 |

---

## Troubleshooting

### If defensive stats show 0
- Check FBRef cache: `fpl-optimizer/cache/fbref_epl_2024_2025.json`
- Player may not have matched - check name spelling

### If xG stats show 0
- Check Understat cache: `fpl-optimizer/cache/understat_epl_2025.json`
- Player may be new or not in Understat database

### If predictions seem off
- Retrain model: `python3 fpl-optimizer/predict_points.py`
- Check training data: `fpl-optimizer/training_data.csv`

---

**Phase 4 Complete - 58 Features Active**
