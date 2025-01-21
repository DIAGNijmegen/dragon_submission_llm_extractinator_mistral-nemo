import json
import re
from pathlib import Path
from typing import List, Union

from dragon_baseline import DragonBaseline

from llm_extractinator import extractinate

import time
import re


class DragonSubmission(DragonBaseline):
    def __init__(self, **kwargs):
        # Example of how to adapt the DRAGON baseline to use a different model
        """
        Adapt the DRAGON baseline to use the joeranbosma/dragon-roberta-base-mixed-domain model.
        Note: when changing the model, update the Dockerfile to pre-download that model.
        """
        super().__init__(**kwargs)
        pass

    def custom_text_cleaning(
        self, text: Union[str, List[str]]
    ) -> Union[str, List[str]]:
        """
        Perform custom text cleaning on the input text.

        Args:
            text (Union[str, List[str]]): The input text to be cleaned. It can be a string or a list of strings.

        Returns:
            Union[str, List[str]]: The cleaned text. If the input is a string, the cleaned string is returned.
            If the input is a list of strings, a list of cleaned strings is returned.

        """
        if isinstance(text, str):
            # Remove HTML tags and URLs:
            text = re.sub(r"<.*?>", "", text)
            text = re.sub(r"http\S+", "", text)

            return text
        else:
            # If text is a list, apply the function to each element
            return [self.custom_text_cleaning(t) for t in text]
        
    def preprocess(self):
        """Preprocess the data."""
        # prepare the reports
        self.remove_common_prefix_from_reports()

        # prepare the labels
        self.scale_labels()
        self.add_dummy_test_labels()
        self.prepare_labels_for_huggingface()
        self.shuffle_train_data()

        # task specific preprocessing
        self.task_specific_preprocessing()

    def task_specific_preprocessing(self):
        """Perform task specific preprocessing."""
        def nli_preprocessing(text_parts):
            return "Sentence 1: " + text_parts[0] + "\n\nSentence 2: " + text_parts[1]
        
        def task015_preprocessing(text_parts):
            return "Roman numeral: " + text_parts[0] + "\n\nText:" + text_parts[1]
        
        def ner_preprocessing(text_parts):
            text = ""
            for part in text_parts:
                text += part + " "
            return text

        nli_tasks = ("014", "103")
        ner_tasks = ("025", "026", "027", "028", "108", "109")

        if any(task in self.task.task_name for task in nli_tasks):
            self.df_test["text"] = self.df_test["text_parts"].apply(nli_preprocessing)
            print("Applied NLI preprocessing")
        elif "015" in self.task.task_name:
            self.df_test["text"] = self.df_test["text_parts"].apply(task015_preprocessing)
            print("Applied Task015 preprocessing")
        elif any(task in self.task.task_name for task in ner_tasks):
            self.df_test["text"] = self.df_test["text_parts"].apply(ner_preprocessing)
            print("Applied NER preprocessing")
        else:
            print("No task specific preprocessing applied")

    def process(self):
        """
        Override the process method to use llm_extractinator for predictions.
        """
        print("Loading data...")
        self.load()
        print("Validating data...")
        self.validate()
        print("Analyzing data...")
        self.analyze()
        print("Preprocessing data...")
        self.preprocess()
        print("Setting up folder structure...")
        self.setup_folder_structure()
        print("Extracting predictions...")
        self.extract_predictions()
        print("Postprocessing predictions...")
        self.postprocess()
        print("Validating predictions...")
        self.verify_predictions()

    def setup_folder_structure(self):
        """
        Create the necessary folders for the LLM to generate predictions.
        """
        self.basepath = Path("/opt/app/llm_extractinator")
        self.basepath.mkdir(exist_ok=True)
        (self.basepath / "data").mkdir(exist_ok=True)
        (self.basepath / "output").mkdir(exist_ok=True)
        (self.basepath / "tasks").mkdir(exist_ok=True)

        self.df_test.to_json(self.basepath / "data" / "test.json", orient="records")

    def extract_predictions(self):
        """
        Use the pre-trained LLM to generate predictions for the test data.

        Args:
            df (DataFrame): The test dataframe containing input data.

        Returns:
            List: Predictions generated by the LLM.
        """
        self.task_id = re.search(r"\d{3}", self.task.task_name).group(0)

        extractinate(
            task_id=self.task_id,
            model_name="mistral-nemo",
            num_examples=0,
            max_context_len=8192,
            num_predict=512,
            translate=False,
            data_dir=self.basepath / "data",
            output_dir=self.basepath / "output",
            task_dir=self.basepath / "tasks",
            n_runs=1,
            verbose=False,
            run_name="run",
        )

    def postprocess(self):
        """
        Post-process the predictions generated by the LLM.
        """

        def print_processing_message(task_id: str) -> None:
            """
            Prints a message indicating the task being processed.
            """
            print(f"Post-processing Task{task_id}...")

        def save_json(data: List, filepath: Path) -> None:
            """
            Save the data to a JSON file.
            """
            with open(filepath, "w") as f:
                json.dump(data, f)

        def wait_for_predictions(self, runpath, timeout=300, interval=10):
            """
            Wait for the predictions to be generated and saved.

            Args:
                timeout (int): Maximum time to wait in seconds.
                interval (int): Interval between checks in seconds.
            """
            start_time = time.time()
            while time.time() - start_time < timeout:
                for folder in runpath.iterdir():
                    if self.task_id in folder.name:
                        print(f"Predictions found in {folder}. Proceeding to postprocess.")
                        return folder
                print("Waiting for predictions to complete...")
                time.sleep(interval)
            raise TimeoutError(f"Predictions for Task {self.task_id} not found within {timeout} seconds.")

        def drop_keys_except(data: List, keys: List[str]) -> List:
            """
            Drop all keys from the dictionary except the specified keys.
            """
            return [
                {key: value for key, value in example.items() if key in keys}
                for example in data
            ]

        runpath = self.basepath / "output" / "run"
        filepath = self.test_predictions_path

        datafolder = wait_for_predictions(self, runpath)

        datapath = datafolder / "nlp-predictions-dataset.json"

        with open(datapath, "r") as file:
            data = json.load(file)

        task_id = f"{int(self.task_id):03}"

        binary_class_ids = [1, 2, 3, 4, 5, 6, 7, 8, 101]
        binary_class_ids = [f"{int(class_id):03}" for class_id in binary_class_ids]

        multi_class_ids = [9, 10, 11, 12, 13, 14, 102, 103]
        multi_class_ids = [f"{int(class_id):03}" for class_id in multi_class_ids]

        single_regression_ids = [19, 20, 21, 22, 23, 106]
        single_regression_ids = [
            f"{int(class_id):03}" for class_id in single_regression_ids
        ]

        if task_id in binary_class_ids:
            print_processing_message(task_id)
            try:
                for example in data:
                    if example["label"] == "True" or example["label"] == True:
                        example["label"] = 1.0
                    if example["label"] == "False" or example["label"] == False:
                        example["label"] = 0.0
                    example[self.task.input_name] = example.pop("label")
                data = drop_keys_except(
                    data, ["uid", self.task.input_name]
                )
            except KeyError:
                print(f"Task {task_id} does not contain 'label' key.")
                pass
            save_json(data=data, filepath=filepath)
        elif task_id in multi_class_ids:
            print_processing_message(task_id)
            try:
                for example in data:
                    example[self.task.input_name] = example.pop(
                        "label"
                    )
                data = drop_keys_except(
                    data, ["uid", self.task.input_name]
                )
            except KeyError:
                print(f"Task {task_id} does not contain 'label' key.")
                pass
            save_json(data=data, filepath=filepath)
        elif task_id in single_regression_ids:
            print_processing_message(task_id)
            try:
                for example in data:
                    example[self.task.input_name] = example.pop("label")
                data = drop_keys_except(data, ["uid", self.task.input_name])
            except KeyError:
                print(f"Task {task_id} does not contain 'label' key.")
                pass
            save_json(data=data, filepath=filepath)
        elif task_id == "015":
            print_processing_message(task_id)
            try:
                for example in data:
                    example[self.task.input_name] = [
                        example.pop("biopsy"),
                        example.pop("cancer"),
                        example.pop("high_grade_dysplasia"),
                        example.pop("hyperplastic_polyps"),
                        example.pop("low_grade_dysplasia"),
                        example.pop("non_informative"),
                        example.pop("serrated_polyps"),
                    ]
                data = drop_keys_except(
                    data, ["uid", self.task.input_name]
                )
                for example in data:
                    for key, value in example.items():
                        if value == "True" or value == True:
                            example[key] = 1.0
                        if value == "False" or value == False:
                            example[key] = 0.0
            except KeyError:
                print(f"Task {task_id} does not contain the correct keys.")
                pass
            save_json(data=data, filepath=filepath)
        elif task_id == "016":
            print_processing_message(task_id)
            try:
                for example in data:
                    example[self.task.input_name] = [
                        example.pop("lesion_1"),
                        example.pop("lesion_2"),
                        example.pop("lesion_3"),
                        example.pop("lesion_4"),
                        example.pop("lesion_5"),
                    ]
                data = drop_keys_except(
                    data, ["uid", self.task.input_name]
                )
                for example in data:
                    for key, value in example.items():
                        if value == "True" or value == True:
                            example[key] = 1.0
                        if value == "False" or value == False:
                            example[key] = 0.0
            except KeyError:
                print(f"Task {task_id} does not contain the correct keys.")
                pass
            save_json(data=data, filepath=filepath)
        elif task_id == "017":
            print_processing_message(task_id)
            try:
                for example in data:
                    example[self.task.input_name] = [
                        example.pop("attenuation"),
                        example.pop("location"),
                    ]
                data = drop_keys_except(
                    data, ["uid", self.task.input_name]
                )
            except KeyError:
                print(f"Task {task_id} does not contain the correct keys.")
                pass
            save_json(data=data, filepath=filepath)
        elif task_id == "018":
            print_processing_message(task_id)
            try:
                for example in data:
                    example[self.task.input_name] = [
                        example.pop("left"),
                        example.pop("right"),
                    ]
                data = drop_keys_except(
                    data, ["uid", self.task.input_name]
                )
            except KeyError:
                print(f"Task {task_id} does not contain the correct keys.")
                pass
            save_json(data=data, filepath=filepath)
        elif task_id == "024":
            print_processing_message(task_id)
            try:
                for example in data:
                    example[self.task.input_name] = [
                        example.pop("lesion_1"),
                        example.pop("lesion_2"),
                        example.pop("lesion_3"),
                        example.pop("lesion_4"),
                        example.pop("lesion_5"),
                    ]
                data = drop_keys_except(data, ["uid", self.task.input_name])
            except KeyError:
                print(f"Task {task_id} does not contain the correct keys.")
                pass
            save_json(data=data, filepath=filepath)
        elif task_id == "025":
            print_processing_message(task_id)
            try:
                for example in data:
                    text_parts = example.pop("text_parts")
                    anonymized_text = example.pop("anonymized_text")
                    ner_target = ["O"] * len("text_parts")

                    # Regex pattern to validate tags containing < and >
                    valid_tag_pattern = re.compile(r"<.*?>")

                    for orig, entity in anonymized_text:
                        # Skip if the tag is invalid
                        if not valid_tag_pattern.match(entity):
                            continue

                        # Tokenize the original text
                        orig_tokens = orig.split()
                        orig_len = len(orig_tokens)

                        if orig_len == 0:
                            continue  # Skip empty entities

                        # Match tokens using a sliding window
                        for i in range(len(text_parts) - orig_len + 1):
                            # Check if the token window matches the entity tokens
                            if text_parts[i:i + orig_len] == orig_tokens:
                                # Label the first token as B-<ENTITY>
                                ner_target[i] = f"B-{entity}"
                                # Label subsequent tokens as I-<ENTITY>
                                for j in range(1, orig_len):
                                    ner_target[i + j] = f"I-{entity}"
                                break  # Stop after the first match to avoid overlapping entities
                    example(self.task.input_name) = ner_target
                data = drop_keys_except(data, ["uid", self.task.input_name])
            except KeyError:
                print(f"Task {task_id} does not contain the correct keys.")
                pass
            save_json(data=data, filepath=filepath)
        elif task_id == "104":
            print_processing_message(task_id)
            try:
                for example in data:
                    example[self.task.input_name] = [
                        example.pop("lesion_1"),
                        example.pop("lesion_2"),
                        example.pop("lesion_3"),
                        example.pop("lesion_4"),
                        example.pop("lesion_5"),
                    ]
                data = drop_keys_except(
                    data, ["uid", self.task.input_name]
                )
                for example in data:
                    for key, value in example.items():
                        if value == "True" or value == True:
                            example[key] = 1.0
                        if value == "False" or value == False:
                            example[key] = 0.0
            except KeyError:
                print(f"Task {task_id} does not contain the correct keys.")
                pass
            save_json(data=data, filepath=filepath)
        elif task_id == "105":
            print_processing_message(task_id)
            try:
                for example in data:
                    example[self.task.input_name] = [
                        example.pop("diagnosis"),
                        example.pop("treatment"),
                    ]
                data = drop_keys_except(
                    data, ["uid", self.task.input_name]
                )
            except KeyError:
                print(f"Task {task_id} does not contain the correct keys.")
                pass
            save_json(data=data, filepath=filepath)
        elif task_id == "107":
            print_processing_message(task_id)
            try:
                for example in data:
                    example[self.task.input_name] = [
                        example.pop("measurement_1"),
                        example.pop("measurement_2"),
                        example.pop("measurement_3"),
                        example.pop("measurement_4"),
                        example.pop("measurement_5"),
                    ]
                data = drop_keys_except(data, ["uid", self.task.input_name])
            except KeyError:
                print(f"Task {task_id} does not contain the correct keys.")
                pass
            save_json(data=data, filepath=filepath)
        elif task_id == "108":
            print_processing_message(task_id)
            try:
                for example in data:
                    text_parts = example.pop("text_parts")
                    anonymized_text = example.pop("anonymized_text")
                    ner_target = ["O"] * len("text_parts")

                    # Regex pattern to validate tags containing < and >
                    valid_tag_pattern = re.compile(r"(PREFIX|SYMPTOM|DIAGNOSIS|STRUCTURE|ROMAN_NUMERAL|NOTE)")

                    for orig, entity in anonymized_text:
                        # Skip if the tag is invalid
                        if not valid_tag_pattern.match(entity):
                            continue

                        # Tokenize the original text
                        orig_tokens = orig.split()
                        orig_len = len(orig_tokens)

                        if orig_len == 0:
                            continue  # Skip empty entities

                        # Match tokens using a sliding window
                        for i in range(len(text_parts) - orig_len + 1):
                            # Check if the token window matches the entity tokens
                            if text_parts[i:i + orig_len] == orig_tokens:
                                # Label the first token as B-<ENTITY>
                                ner_target[i] = f"B-{entity}"
                                # Label subsequent tokens as I-<ENTITY>
                                for j in range(1, orig_len):
                                    ner_target[i + j] = f"I-{entity}"
                                break  # Stop after the first match to avoid overlapping entities
                    example(self.task.input_name) = ner_target
                data = drop_keys_except(data, ["uid", self.task.input_name])
            except KeyError:
                print(f"Task {task_id} does not contain the correct keys.")
                pass
            save_json(data=data, filepath=filepath)
        elif task_id == "109":
            print_processing_message(task_id)
            try:
                for example in data:
                    text_parts = example.pop("text_parts")
                    anonymized_text = example.pop("anonymized_text")
                    
                    # Initialize ner_target with lists for overlapping tags
                    ner_target = [[] for _ in range(len(text_parts))]

                    # Regex pattern to validate tags containing < and >
                    valid_tag_pattern = re.compile(r".*")

                    for idx, (orig, entity) in enumerate(anonymized_text):
                        # Skip if the tag is invalid
                        if not valid_tag_pattern.match(entity):
                            continue

                        # Tokenize the original text
                        orig_tokens = orig.split()
                        orig_len = len(orig_tokens)

                        if orig_len == 0:
                            continue  # Skip empty entities

                        # Match tokens using a sliding window
                        for i in range(len(text_parts) - orig_len + 1):
                            # Check if the token window matches the entity tokens
                            if text_parts[i:i + orig_len] == orig_tokens:
                                # Assign B-<ENTITY> to the first token
                                ner_target[i].append(f"B-{idx}-lesion")
                                # Assign I-<ENTITY> to subsequent tokens
                                for j in range(1, orig_len):
                                    ner_target[i + j].append(f"I-{idx}-lesion")
                                break  # Stop after the first match for this entity

                    # Convert lists to strings, using 'O' if the list is empty
                    ner_target = ["O" if not tags else ",".join(tags) for tags in ner_target]

                    example[self.task.input_name] = ner_target
                data = drop_keys_except(data, ["uid", self.task.input_name])
            except KeyError:
                print(f"Task {task_id} does not contain the correct keys.")
                pass
            save_json(data=data, filepath=filepath)


if __name__ == "__main__":
    DragonSubmission().process()
