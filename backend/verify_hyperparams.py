import requests
import json

url = "http://localhost:8000/nfl/train/classification?test_start=2023"
payload = {
    "hyperparameters": {
        "n_estimators": 10,
        "max_depth": 5
    }
}
headers = {"Content-Type": "application/json"}

try:
    response = requests.post(url, json=payload, headers=headers)
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        print("Response JSON:")
        print(json.dumps(response.json(), indent=2))
        
        # Check if hyperparameters are in metrics (if we implemented that)
        metrics = response.json().get('metrics', {})
        print("\nMetrics Hyperparameters:")
        print(metrics.get('hyperparameters'))
    else:
        print("Error Response:")
        print(response.text)

except Exception as e:
    print(f"Request failed: {e}")
