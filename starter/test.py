import json

loyalty_points = 4500
tier = "Gold"
order_total = 150
product_category = "standard"
earn_rates = {"standard": 1, "device": 2, "fresh": 5}
tier_rates = {"Silver": 0.00, "Gold": 0.10, "Platinum": 0.15}

floor_order_cap_in_points = ((order_total*0.5*0.01)//500)*500
floor_points = (loyalty_points//500)*500

if floor_order_cap_in_points <= loyalty_points:
    points_redeemed = min(floor_order_cap_in_points, floor_points)
else:
    points_redeemed = floor_points

tier_discount = tier_rates.get(tier, 0)
order_subtotal = order_total - (points_redeemed*0.01)

final_total = order_subtotal * (1-tier_discount)
total_savings = order_total-final_total
points_earned = (final_total*0.01)*earn_rates.get(product_category,1)
remaining_points = loyalty_points - points_redeemed + points_earned

response = {
            "final_total":round(final_total, 2),
            "total_savings":round(total_savings, 2),
            "points_earned":int(points_earned),
            "remaining_points":int(remaining_points)
}
        
print(json.dumps(response, indent=4))