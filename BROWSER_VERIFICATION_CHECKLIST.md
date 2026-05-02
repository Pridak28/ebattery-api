# Browser UI Verification Checklist

**Date:** December 4, 2025
**App URL:** http://localhost:3000/fr-simulator
**Backend API:** http://localhost:8000

## Summary of Changes Made

### Frontend Fixes (4 changes)
1. ✅ **Section 14 (Lines 1237-1251)**: Added disclaimer warning users that scenarios use simplified formulas
2. ✅ **Section 9 (Lines 285-298)**: Net profit already correctly using backend data (`row.net_profit_eur`)
3. ✅ **Section 13 (Line 1191)**: Removed `.slice(0, 24)` - table now shows ALL rows
4. ✅ **Section 8 (Lines 970-976)**: Fixed average activation price to use weighted average by energy

### Backend API Tests
- ✅ All 9 API endpoints tested and passing
- ✅ Battery constraint verified: 900 MWh/month limit enforced
- ✅ Multi-product constraint verified: aFRR+ and aFRR- share 900 MWh budget
- ✅ Annualization verified: Uses `months_count` correctly

---

## Browser Verification Steps

### Prerequisites
1. Ensure backend is running: http://localhost:8000
2. Ensure frontend is running: http://localhost:3000
3. Open http://localhost:3000/fr-simulator in browser
4. Open browser DevTools (F12) to check for errors

---

## Test Suite 1: Main Simulation - Single Product

### Configuration
- Battery: 30 MWh
- Power: 15 MW
- Round-trip efficiency: 90%
- aFRR+ enabled: 15 MW, capacity price 25 EUR/MW/h, activation rate 10%
- aFRR- disabled
- Energy cost: 80 EUR/MWh
- Date range: 2024-07-01 to 2024-12-31 (6 months)

### Verification Steps

#### ✅ Section 3: Executive Summary (Lines 712-795)
- [ ] **Check months_count**: Should show "Based on 6 months of data"
- [ ] **Annual Revenue**: Should be ~€5.24M (from €2.62M × 2)
- [ ] **Monthly Average**: Should be ~€437K (€5.24M ÷ 12)
- [ ] **Total Revenue**: Should be €2.62M for 6 months
- [ ] **Net Profit Margin**: Should be displayed as percentage

#### ✅ Section 4: KPI Cards (Lines 712-795)
- [ ] **Revenue per MW**: Should show annualized value
- [ ] **Capacity Revenue**: Should be ~€1.8M - €2.1M
- [ ] **Activation Revenue**: Should be ~€600K - €700K
- [ ] **Energy Cost**: Should show negative value (red)

#### ✅ Section 8: Key Metrics Panel (Lines 953-986)
- [ ] **Avg Activation Price**: Now uses weighted average (fix applied)
  - Should show reasonable value (100-200 EUR/MWh)
  - Value should make sense (not artificially averaged)

#### ✅ Section 9: Monthly Revenue Trend Chart (Lines 992-1053)
- [ ] **Chart displays 6 data points** (Jul-Dec 2024)
- [ ] **Stacked area shows**: Capacity (blue) + Activation (green)
- [ ] **Net profit line** visible and correct
- [ ] **Hover tooltip** shows all values correctly

#### ✅ Section 10: Product Comparison (Lines 1055-1100)
- [ ] **Only aFRR+ bar visible** (aFRR- disabled)
- [ ] **Total revenue matches** Section 3 total

#### ✅ Section 13: Monthly Breakdown Table (Lines 1172-1227)
- [ ] **Table shows exactly 6 rows** (one per month)
- [ ] **All months visible**: Jul, Aug, Sep, Oct, Nov, Dec
- [ ] **No truncation** - all 6 rows displayed (fix applied)
- [ ] **Activation energy per month**: Should be ≤900 MWh
- [ ] **Each row shows**: Month, Product (aFRR+), Slots, Capacity Revenue, Activation Revenue, Energy, Cost, Net Profit

#### ✅ Section 14: Scenarios Comparison (Lines 1228-1315)
- [ ] **⚠️ Disclaimer banner visible** (amber background, warning icon)
- [ ] **Disclaimer text**: "Simplified Estimates Only" and warning about using main simulation
- [ ] **Table still displays** with 4 scenarios (Pessimistic, Base, Moderate, Optimistic)

---

## Test Suite 2: Main Simulation - Two Products

### Configuration
- Battery: 30 MWh
- Power: 15 MW
- Round-trip efficiency: 90%
- **aFRR+ enabled**: 15 MW, capacity price 25 EUR/MW/h, activation rate 10%
- **aFRR- enabled**: 15 MW, capacity price 20 EUR/MW/h, activation rate 10%
- Energy cost: 80 EUR/MWh
- Date range: 2024-07-01 to 2024-12-31 (6 months)

### Verification Steps

#### ✅ Section 3: Executive Summary
- [ ] **Months count**: Still shows "Based on 6 months" (not 12!)
- [ ] **Total revenue**: Higher than single product (~€3.9M for 6 months)
- [ ] **Annual revenue**: Correctly annualized to 12 months (~€7.8M)

#### ✅ Section 8: Avg Activation Price
- [ ] **Weighted average** shown (not simple average of both products)
- [ ] **Value makes sense**: Should be between aFRR+ and aFRR- average prices
- [ ] **Not meaningless**: Previous bug would show nonsensical value

#### ✅ Section 9: Monthly Chart
- [ ] **Chart shows 6 months** (not 12)
- [ ] **Each month aggregates both products**: aFRR+ and aFRR- combined
- [ ] **Stacked area shows total** of both products
- [ ] **Net profit calculation correct** (using updated values, not old)

#### ✅ Section 10: Product Comparison
- [ ] **Two bars visible**: aFRR+ and aFRR-
- [ ] **aFRR+ revenue higher** than aFRR- (higher capacity price)

#### ✅ Section 13: Monthly Breakdown Table
- [ ] **Table shows 12 rows** (6 months × 2 products)
- [ ] **ALL 12 rows visible** - no truncation at row 24 (fix verified)
- [ ] **Products alternate or grouped by month**:
  - Jul aFRR+, Jul aFRR-, Aug aFRR+, Aug aFRR-, etc.
- [ ] **Shared battery constraint**: For each month, sum(aFRR+ energy + aFRR- energy) ≤ 900 MWh
- [ ] **Example check for July**:
  - Jul aFRR+: ~450 MWh
  - Jul aFRR-: ~450 MWh
  - Total: 900 MWh ✅

---

## Test Suite 3: DAMAS Price Explorer (Sections 15-18)

### Steps
1. Scroll down to "DAMAS Price Explorer" section
2. Select date: **2024-12-03**
3. Power: 15 MW

### Verification
- [ ] **96 slots displayed** in line chart (24 hours × 4 slots/hour)
- [ ] **Hourly table shows every 4th slot** (0:00, 1:00, 2:00, etc.)
- [ ] **Daily summary matches** sum of all 96 slots
- [ ] **aFRR+ and aFRR- prices** shown separately
- [ ] **DAMAS link** present and points to Transelectrica

---

## Test Suite 4: Bidding Optimizer (Sections 19-22)

### Steps
1. Scroll to "Bidding Optimizer" section
2. Select date: **2024-12-03**
3. Adjust acceptance rate slider: **60% → 80% → 90%**

### Verification
- [ ] **Bid prices decrease as acceptance increases**:
  - 90% acceptance → lowest capacity bid
  - 60% acceptance → highest capacity bid
- [ ] **Revenue estimates update** dynamically
- [ ] **Product recommendation** shows aFRR+ or aFRR-

### Annual Projection Test
1. Change strategy: **Conservative → Balanced → Aggressive**

### Verification
- [ ] **Annual revenue increases**:
  - Conservative (90% acceptance): ~€4.1M
  - Balanced (80% acceptance): ~€4.4M
  - Aggressive (60% acceptance): ~€4.7M
- [ ] **Monthly projections** sum close to annual total
- [ ] **Acceptance rates displayed correctly**

---

## Test Suite 5: Safe Bid Calculator (Sections 23-26)

### Steps
1. Scroll to "Safe Bid Calculator" section
2. Power: 15 MW
3. Move acceptance slider: **80% → 90% → 95%**

### Verification
- [ ] **Safe bid prices decrease** with higher acceptance
- [ ] **Annual revenue updates** based on strategy
- [ ] **Comparison table** shows safe vs aggressive
- [ ] **Market context** displays percentiles correctly
- [ ] **Strategy recommendation** based on battery constraints

---

## Critical Validation Rules

### ✅ Rule 1: Battery Throughput Limit
**Rule:** No month should exceed 900 MWh total activation energy
**How to check:**
- Section 13: Monthly Breakdown Table
- Look at "Energy (MWh)" column
- For single product: Each row ≤ 900 MWh
- For two products: Sum of both products per month ≤ 900 MWh

### ✅ Rule 2: Annualization Formula
**Rule:** `annual_revenue = total_revenue × (12 / months_count)`
**How to check:**
- Section 3: Note the months_count (e.g., 6 months)
- Note total_revenue (e.g., €2.62M)
- Calculate: €2.62M × (12/6) = €5.24M
- Compare to displayed annual_revenue

### ✅ Rule 3: Multi-Product Aggregation
**Rule:** When both aFRR+ and aFRR- enabled, frontend correctly sums revenues per month
**How to check:**
- Section 13: Monthly table with 12 rows (6 months × 2 products)
- Pick any month (e.g., July)
- Note aFRR+ revenue for July
- Note aFRR- revenue for July
- Section 9: Monthly chart for July should show sum of both

### ✅ Rule 4: Weighted Averages
**Rule:** Activation price should be weighted by energy, not simple average
**How to check:**
- Run simulation with both aFRR+ and aFRR- enabled
- Section 8: Avg Activation Price
- Value should be weighted by which product delivered more energy
- Should NOT be simple arithmetic mean of the two prices

### ✅ Rule 5: No Simplified Formulas in Section 14
**Rule:** Section 14 disclaimer must warn users about simplified calculations
**How to check:**
- Section 14: Scenarios Comparison Table
- Look for amber warning banner at top
- Should say "⚠️ Simplified Estimates Only"
- Should recommend using main simulation

---

## Browser Console Checks

Open DevTools Console (F12 → Console) and verify:

- [ ] **No React errors** (red error messages)
- [ ] **No API call failures** (check Network tab)
- [ ] **No TypeScript errors** (check terminal running `npm run dev`)
- [ ] **Charts render correctly** (no Recharts warnings)

---

## Expected Outcomes Summary

### After All Fixes Applied:

#### Single Product (aFRR+ only, 6 months Jul-Dec 2024):
- Total Revenue: €2.62M
- Annual Revenue: €5.24M
- Monthly Average: €437K
- Activation Energy: ≤900 MWh/month
- Months Count: 6
- Table Rows: 6

#### Two Products (aFRR+ and aFRR-, 6 months Jul-Dec 2024):
- Total Revenue: €3.9M
- Annual Revenue: €7.8M
- Monthly Average: €650K
- Total Activation Energy per Month: ≤900 MWh (SHARED)
- Months Count: 6 (unique months)
- Table Rows: 12 (6 × 2)

#### Section 14 Scenarios:
- ⚠️ Disclaimer visible
- User warned about simplified estimates
- Scenarios still displayed for reference

---

## Final Checklist

- [ ] All frontend fixes visually verified in browser
- [ ] Backend API tests all passing (9/9)
- [ ] Battery constraints enforced (900 MWh/month)
- [ ] Multi-product aggregation correct
- [ ] Weighted averages implemented
- [ ] Section 14 disclaimer displayed
- [ ] No browser console errors
- [ ] All sections display correct data

---

## Notes

**If you find any issues:**
1. Check browser console for errors
2. Verify backend API is running (http://localhost:8000)
3. Check that frontend compiled successfully (no TypeScript errors)
4. Review test results in `test_results/` directory
5. Compare actual values to expected outcomes above

**Test Results Location:** `/Users/seversilaghi/Documents/battery-analytics-pro/test_results/`

**Backend logs:** Check terminal running `uvicorn app.main:app --reload`
**Frontend logs:** Check terminal running `npm run dev`
