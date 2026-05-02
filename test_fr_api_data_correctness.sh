#!/bin/bash
# test_fr_api_data_correctness.sh
# Comprehensive test script for FR API data correctness verification

BASE_URL="http://localhost:8000/api/v1/fr"
OUTPUT_DIR="test_results"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "=== Testing FR API Data Correctness ==="
echo "Output directory: $OUTPUT_DIR"

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Test 1: Main Simulation - Single Product
echo -e "\n${YELLOW}[Test 1]${NC} Single Product Simulation (aFRR+ only)"
curl -s -X POST "$BASE_URL/simulate" \
  -H "Content-Type: application/json" \
  -d '{
    "capacity_mwh": 30,
    "round_trip_efficiency": 0.90,
    "afrr_up": {"enabled": true, "power_mw": 15, "capacity_price_eur_mw_h": 25, "activation_rate": 0.10},
    "afrr_down": {"enabled": false, "power_mw": 0},
    "energy_cost_eur_mwh": 80,
    "start_date": "2024-07-01",
    "end_date": "2024-12-31"
  }' | python3 -m json.tool > "$OUTPUT_DIR/test1_single_product.json"

if [ -f "$OUTPUT_DIR/test1_single_product.json" ]; then
  echo -e "${GREEN}✓${NC} Test 1 completed"
  echo "  Verify:"
  echo "    - months_count should be 6 (Jul-Dec 2024)"
  echo "    - monthly_results should have 6 rows"
  echo "    - Max activation_energy_mwh per month should be ≤900 MWh"

  # Extract key metrics
  MONTHS_COUNT=$(cat "$OUTPUT_DIR/test1_single_product.json" | grep -o '"months_count": [0-9]*' | head -1 | grep -o '[0-9]*')
  TOTAL_REVENUE=$(cat "$OUTPUT_DIR/test1_single_product.json" | grep -o '"total_revenue_eur": [0-9.]*' | head -1 | grep -o '[0-9.]*')
  echo "    - months_count: $MONTHS_COUNT"
  echo "    - total_revenue_eur: €${TOTAL_REVENUE}"
else
  echo -e "${RED}✗${NC} Test 1 failed"
fi

# Test 2: Main Simulation - Two Products
echo -e "\n${YELLOW}[Test 2]${NC} Two Products Simulation (aFRR+ and aFRR-)"
curl -s -X POST "$BASE_URL/simulate" \
  -H "Content-Type: application/json" \
  -d '{
    "capacity_mwh": 30,
    "round_trip_efficiency": 0.90,
    "afrr_up": {"enabled": true, "power_mw": 15, "capacity_price_eur_mw_h": 25, "activation_rate": 0.10},
    "afrr_down": {"enabled": true, "power_mw": 15, "capacity_price_eur_mw_h": 20, "activation_rate": 0.10},
    "energy_cost_eur_mwh": 80,
    "start_date": "2024-07-01",
    "end_date": "2024-12-31"
  }' | python3 -m json.tool > "$OUTPUT_DIR/test2_two_products.json"

if [ -f "$OUTPUT_DIR/test2_two_products.json" ]; then
  echo -e "${GREEN}✓${NC} Test 2 completed"
  echo "  Verify:"
  echo "    - months_count should be 6 (unique months)"
  echo "    - monthly_results should have 12 rows (6 months × 2 products)"
  echo "    - For each month: aFRR_up_energy + aFRR_down_energy ≤ 900 MWh"

  MONTHS_COUNT=$(cat "$OUTPUT_DIR/test2_two_products.json" | grep -o '"months_count": [0-9]*' | head -1 | grep -o '[0-9]*')
  TOTAL_REVENUE=$(cat "$OUTPUT_DIR/test2_two_products.json" | grep -o '"total_revenue_eur": [0-9.]*' | head -1 | grep -o '[0-9.]*')
  echo "    - months_count: $MONTHS_COUNT"
  echo "    - total_revenue_eur: €${TOTAL_REVENUE}"
else
  echo -e "${RED}✗${NC} Test 2 failed"
fi

# Test 3: Slot Prices (DAMAS Explorer)
echo -e "\n${YELLOW}[Test 3]${NC} Slot Prices for specific date (2024-12-03)"
curl -s "$BASE_URL/slot-prices/2024-12-03?power_mw=15" | python3 -m json.tool > "$OUTPUT_DIR/test3_slot_prices.json"

if [ -f "$OUTPUT_DIR/test3_slot_prices.json" ]; then
  echo -e "${GREEN}✓${NC} Test 3 completed"
  echo "  Verify:"
  echo "    - slot_prices array should have 96 entries (24h × 4 slots/hour)"
  echo "    - Sum of slot revenues should equal daily_summary.total_revenue_eur"

  SLOTS_COUNT=$(cat "$OUTPUT_DIR/test3_slot_prices.json" | grep -c '"slot":')
  echo "    - Number of slots: $SLOTS_COUNT"
else
  echo -e "${RED}✗${NC} Test 3 failed"
fi

# Test 4: Optimal Bids
echo -e "\n${YELLOW}[Test 4]${NC} Optimal Bids with different acceptance rates"
for rate in 0.60 0.80 0.90; do
  echo "  Testing acceptance rate: $rate"
  curl -s "$BASE_URL/optimal-bids/2024-12-03?power_mw=15&target_acceptance=$rate" \
    | python3 -m json.tool > "$OUTPUT_DIR/test4_optimal_bids_${rate}.json"

  if [ -f "$OUTPUT_DIR/test4_optimal_bids_${rate}.json" ]; then
    echo -e "    ${GREEN}✓${NC} Rate $rate completed"
  else
    echo -e "    ${RED}✗${NC} Rate $rate failed"
  fi
done

echo "  Verify:"
echo "    - 90% acceptance should have lower capacity bid than 60%"
echo "    - Daily revenue = capacity_component + activation_component"

# Test 5: Revenue Projection
echo -e "\n${YELLOW}[Test 5]${NC} 12-Month Revenue Projection"
for strategy in conservative balanced aggressive; do
  echo "  Testing strategy: $strategy"
  curl -s "$BASE_URL/revenue-projection?power_mw=15&strategy=$strategy" \
    | python3 -m json.tool > "$OUTPUT_DIR/test5_projection_${strategy}.json"

  if [ -f "$OUTPUT_DIR/test5_projection_${strategy}.json" ]; then
    echo -e "    ${GREEN}✓${NC} Strategy $strategy completed"
    ANNUAL=$(cat "$OUTPUT_DIR/test5_projection_${strategy}.json" | grep -o '"total_projected_annual_revenue": [0-9.]*' | head -1 | grep -o '[0-9.]*')
    echo "       Annual revenue: €${ANNUAL}"
  else
    echo -e "    ${RED}✗${NC} Strategy $strategy failed"
  fi
done

echo "  Verify:"
echo "    - Revenue ranking: aggressive > balanced > conservative"
echo "    - Acceptance rates: conservative=0.90, balanced=0.80, aggressive=0.60"

# Test 6: Safe Bid Calculator
echo -e "\n${YELLOW}[Test 6]${NC} Safe Bid Calculator"
curl -s "$BASE_URL/safe-bid-calculator?power_mw=15&target_acceptance=0.90" \
  | python3 -m json.tool > "$OUTPUT_DIR/test6_safe_bids.json"

if [ -f "$OUTPUT_DIR/test6_safe_bids.json" ]; then
  echo -e "${GREEN}✓${NC} Test 6 completed"
  echo "  Verify:"
  echo "    - Percentile should be 10 for 90% acceptance"
  echo "    - Annual revenue should respect 900 MWh/month × 12 = 10,800 MWh/year limit"

  ANNUAL=$(cat "$OUTPUT_DIR/test6_safe_bids.json" | grep -o '"annual_revenue_eur": [0-9.]*' | head -1 | grep -o '[0-9.]*')
  echo "    - Annual revenue: €${ANNUAL}"
else
  echo -e "${RED}✗${NC} Test 6 failed"
fi

# Test 7: Bidding Strategy Analysis
echo -e "\n${YELLOW}[Test 7]${NC} Bidding Strategy Analysis"
curl -s "$BASE_URL/bidding-strategy?start_date=2024-07-01&end_date=2024-12-31" \
  | python3 -m json.tool > "$OUTPUT_DIR/test7_bidding_strategy.json"

if [ -f "$OUTPUT_DIR/test7_bidding_strategy.json" ]; then
  echo -e "${GREEN}✓${NC} Test 7 completed"
  echo "  Verify:"
  echo "    - Contains strategy recommendations for different percentiles"
  echo "    - Shows aFRR+ vs aFRR- profitability comparison"
else
  echo -e "${RED}✗${NC} Test 7 failed"
fi

# Test 8: Available Dates
echo -e "\n${YELLOW}[Test 8]${NC} Available Dates"
curl -s "$BASE_URL/available-dates" | python3 -m json.tool > "$OUTPUT_DIR/test8_available_dates.json"

if [ -f "$OUTPUT_DIR/test8_available_dates.json" ]; then
  echo -e "${GREEN}✓${NC} Test 8 completed"
  DATES_COUNT=$(cat "$OUTPUT_DIR/test8_available_dates.json" | grep -c '"date":')
  echo "  Available dates: $DATES_COUNT"
else
  echo -e "${RED}✗${NC} Test 8 failed"
fi

# Test 9: FR Products List
echo -e "\n${YELLOW}[Test 9]${NC} FR Products List"
curl -s "$BASE_URL/products" | python3 -m json.tool > "$OUTPUT_DIR/test9_products.json"

if [ -f "$OUTPUT_DIR/test9_products.json" ]; then
  echo -e "${GREEN}✓${NC} Test 9 completed"
  echo "  Verify products: aFRR+, aFRR-, mFRR+, mFRR-"
else
  echo -e "${RED}✗${NC} Test 9 failed"
fi

# Summary
echo -e "\n${YELLOW}=== Test Summary ===${NC}"
echo "All test results saved to: $OUTPUT_DIR/"
echo ""
echo "Manual verification required:"
echo "  1. Check months_count vs monthly_results.length consistency"
echo "  2. Verify activation energy ≤ 900 MWh/month per battery"
echo "  3. Confirm multi-product simulations share battery constraint"
echo "  4. Validate annualization: annual_revenue = total_revenue × (12/months_count)"
echo "  5. Ensure weighted averages used for activation prices"
echo ""
echo -e "${GREEN}All tests complete.${NC} Review JSON files in $OUTPUT_DIR/ for detailed verification."
