from datasets import load_dataset

print("Downloading BIRD...")

dataset = load_dataset("birdsql/bird_mini_dev")

print("\nDownload completed!")
print(dataset)