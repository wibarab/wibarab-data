from acdh_tei_pyutils.tei import TeiReader
from pathlib import Path
import os
import json
import re

nsmap = {
    "tei": "http://www.tei-c.org/ns/1.0",
    "xml": "http://www.w3.org/XML/1998/namespace",
    "wib": "https://wibarab.acdh.oeaw.ac.at/langDesc",
}


def process_files(directory):
    """
    Process all TEI files in directory while excluding folders and templates.
    """
    processed_data = {}
    errors = set()
    for file_name in os.listdir(directory):
        file_path = Path(directory, file_name)
        if file_path.is_file() and "template" not in file_name:
            try:
                doc = TeiReader(file_path.as_posix())
                processed_data.update({file_path.as_posix(): doc})
            except (SyntaxError, OSError) as e:
                errors.add(f"Error processing file {file_name}: {e}")
    return processed_data, errors


def first_pass_features(documents):
    """
    First pass through the feature files.
    Extract unique combinations of places and associated varieties from the feature files.
    Get the feature name and parent category for each feature.
    """
    place_variety_combinations = set()
    ft_name_dict = {}
    parent_categories = {}
    for doc in documents.values():
        ft_id = doc.tree.getroot().get("{http://www.w3.org/XML/1998/namespace}id")
        # Get the feature name from the document
        ft_name_dict[ft_id] = doc.create_plain_text(
            doc.any_xpath(".//tei:titleStmt/tei:title")[0]
        )
        category = doc.any_xpath(".//tei:profileDesc/tei:textClass/tei:catRef/@target")
        if category and category[0].startswith("dmp:"):
            category = category[0].replace("dmp:", "")
        else:
            print("Wrong prefix or missing parent category for ", ft_id)
            category = "Missing"
        parent_categories[ft_id] = category
        place_names = doc.any_xpath("//tei:placeName/@ref")
        for place_id in place_names:
            if place_id:
                # Extract varieties associated with the current place from the document
                varieties = doc.any_xpath(
                    f'//tei:placeName[@ref="{place_id}"]/following-sibling::tei:lang/@corresp'
                )
                # Check if there are no varieties associated with the place
                if not varieties:
                    # Add a placeholder value to represent the absence of a variety
                    place_variety_combinations.add((place_id, "no_variety"))
                else:
                    for variety in varieties:
                        # Remove unnecessary parts from the variety id
                        variety = (
                            variety.split("\\")[-1].split("_")[-1].replace(".xml", "")
                        )
                        place_variety_combinations.add((place_id, variety))
    return place_variety_combinations, ft_name_dict, parent_categories


def get_geo_info(place_variety_combinations, geo_doc):
    """
    Get basic geographical information for each place-variety combination from the geo data XML file.
    """
    geo_features = []
    for place_id, variety in place_variety_combinations:
        if place_id:
            geo_xml_id = place_id.split(":")[1]
            location_el = geo_doc.any_xpath(
                f'//tei:place[@xml:id="{geo_xml_id}"]/tei:location'
            )
            if location_el:
                geo_el = location_el[0].find('tei:geo[@decls="#dd"]', namespaces=nsmap)
                if geo_el is not None:
                    coordinates = re.split(r"[\s,]+", geo_doc.create_plain_text(geo_el))
                    # Reverse coordinates from lat-long to long-lat for GeoJSON
                    lng_lat = [float(coord) for coord in reversed(coordinates) if coord]
                else:
                    lng_lat = []
                name = " / ".join(
                    geo_doc.any_xpath(
                        f'//tei:place[@xml:id="{geo_xml_id}"]//tei:placeName/text()'
                    )
                )
                # Create feature with place_id, variety, and name
                feature = {
                    "type": "Feature",
                    "id": f"{place_id}+{variety}",
                    "geometry": {"type": "Point", "coordinates": lng_lat},
                    "properties": {"name": name, "variety": variety},
                }
                geo_features.append(feature)
    geo_features.sort(key=lambda feature: feature["id"])
    return geo_features


def get_bibl_data(bibl_doc):
    """
    Get id, short citation and cert for each source
    """
    bibl_data = {}
    for source in bibl_doc.any_xpath("//tei:biblStruct"):
        source_id = source.get("{http://www.w3.org/XML/1998/namespace}id")
        short_cit = source.get("n")
        decade_dc = source.xpath(
            ".//tei:note[@type='dataCollection']/tei:date/text()", namespaces=nsmap
        )
        if len(decade_dc) > 1:
            print("Multiple data collection dates found for source", source_id)
        cert = source.xpath(
            ".//tei:note[@type='dataCollection']/tei:date/@cert", namespaces=nsmap
        )
        link = source.get("corresp")
        bibl_data[source_id] = {
            "short_cit": short_cit,
            "link": link,
            "decade_dc": (
                {
                    decade: cert if cert else "N/A"
                    for decade, cert in zip(decade_dc, cert)
                }
                if decade_dc
                else {"N/A": "N/A"}
            ),
        }
    return bibl_data


def get_feature_data(geo_features, documents, bibl_data):
    """
    Get all linguistic feature data for each place from the XML documents.
    """
    f_names_count = {}
    for feature in geo_features:
        place_id, variety_id = feature["id"].split("+")
        if variety_id != "no_variety":
            # Match both place and variety
            feature_xpath = f'//tei:placeName[@ref="{place_id}"]/following-sibling::tei:lang[@corresp="..\\profiles\\vicav_profile_{variety_id}.xml"]'
            fvo_xpath = f'//wib:featureValueObservation[tei:placeName[@ref="{place_id}"]/following-sibling::tei:lang[@corresp="..\\profiles\\vicav_profile_{variety_id}.xml"]]'
        else:
            # Match place without variety
            feature_xpath = f'//tei:placeName[@ref="{place_id}" and not(following-sibling::tei:lang)]'
            fvo_xpath = f'//wib:featureValueObservation[tei:placeName[@ref="{place_id}" and not(following-sibling::tei:lang)]]'
        # Create dictionary to store the features and their values documented for the current place
        documented_features = {}
        for doc in documents.values():
            # Match the place_id and variety_id, considering that some places may have no associated variety
            if doc.any_xpath(feature_xpath):
                ft_id = doc.tree.getroot().get(
                    "{http://www.w3.org/XML/1998/namespace}id"
                )
                fv_dict = {}
                ## this shouldn't be necessary if all features have different xml:ids
                if ft_id in documented_features:
                    print(ft_id + ": duplicate feature id")
                for fvo in doc.tree.xpath(
                    fvo_xpath,
                    namespaces=nsmap,
                ):
                    # Get & add mandatory information for fvos first (based on ODD)
                    fv_name_tag = fvo.find("./tei:name", namespaces=nsmap)
                    fv_ref = fv_name_tag.get("ref")
                    if fv_ref == "":
                        fv_name = "Missing"
                    else:
                        fv_ref = fv_ref.lstrip("#")
                        label_element = doc.tree.xpath(
                            f"//tei:item[@xml:id='{fv_ref}']/tei:label",
                            namespaces=nsmap,
                        )
                        if label_element:
                            fv_name = label_element[0].text
                        else:
                            fv_name = "Missing"
                    fv_data = {fv_name: {}}
                    if fv_name in fv_dict:
                        fv_data = fv_dict
                    source_refs = [
                        x.get("corresp")
                        for x in fvo.findall("./tei:bibl", namespaces=nsmap)
                    ]
                    fv_data[fv_name].setdefault("sources", {})
                    for ref in source_refs:
                        if ref:
                            if ref.startswith("zot:"):
                                bibl_id = ref.replace("zot:", "")
                                if bibl_id:
                                    if bibl_id in bibl_data:
                                        fv_data[fv_name]["sources"][bibl_id] = (
                                            bibl_data[bibl_id]
                                        )
                                    else:
                                        print(
                                            "Missing source data for",
                                            bibl_id,
                                            source_refs,
                                        )
                            elif ref.startswith("src:"):
                                bibl_id = ref.replace("src:", "")
                                # WATCHME - placeholder for sources not in Zotero
                                fv_data[fv_name]["sources"][bibl_id] = {
                                    "short_cit": bibl_id,
                                    "link": "",
                                    "decade_dc": {"2020s": "high"},
                                }
                            else:
                                print("Unknown source reference format:", ref)
                                continue

                    # Get & add other optional elements (based on ODD)
                    # Person group
                    pers_group = fvo.findall("./tei:personGrp", namespaces=nsmap)
                    if pers_group:
                        new_pg = {(x.get("role"), x.get("corresp")) for x in pers_group}
                        current_pg = {
                            (k, v)
                            for d in fv_data[fv_name].get("person_groups", [])
                            for k, v in d.items()
                        }
                        fv_data[fv_name]["person_groups"] = [
                            dict([t]) for t in list(current_pg | new_pg)
                        ]
                    # Source representation
                    src_reps = fvo.findall(
                        './tei:cit[@type="sourceRepresentation"]/tei:quote',
                        namespaces=nsmap,
                    )
                    valid_src_reps = [
                        x.text
                        for x in src_reps
                        if x.text is not None and len(x.text) > 0
                    ]
                    if valid_src_reps:
                        existing_scr_reps = fv_data[fv_name].setdefault(
                            "source_representations", []
                        )
                        existing_scr_reps.extend(valid_src_reps)
                        fv_data[fv_name]["source_representations"] = list(
                            set(existing_scr_reps)
                        )

                    # Examples
                    examples = fvo.findall(
                        './tei:cit[@type="example"]/tei:quote', namespaces=nsmap
                    )
                    valid_examples = [
                        x.text
                        for x in examples
                        if x.text is not None and len(x.text) > 0
                    ]
                    if valid_examples:
                        existing_examples = fv_data[fv_name].setdefault("examples", [])
                        existing_examples.extend(valid_examples)
                        # Remove duplicates
                        fv_data[fv_name]["examples"] = list(set(existing_examples))
                    # Notes
                    notes = fvo.findall(
                        './tei:cit[@type="note"]/tei:quote', namespaces=nsmap
                    )
                    valid_notes = [
                        x.text for x in notes if x.text is not None and len(x.text) > 0
                    ]
                    if valid_notes:
                        existing_notes = fv_data[fv_name].setdefault("notes", [])
                        existing_notes.extend(valid_notes)
                        fv_data[fv_name]["notes"] = list(set(existing_notes))

                    fv_dict.update(fv_data)
                    f_names_count[ft_id] = f_names_count.get(ft_id, 0) + 1

                # documented_features.update({ft_id: fv_dict})
                documented_features[ft_id] = fv_dict
        feature["properties"].update(documented_features)

    return geo_features, f_names_count


def write_geojson(output_file, geojson_data):
    with open(output_file, "w", encoding="utf-8") as geojson_file:
        json.dump(
            geojson_data, geojson_file, ensure_ascii=False, indent=2, sort_keys=True
        )


def main():
    # Path to the featuredb, adjust if necessary
    data_home = os.path.join(".", "featuredb")
    # Paths to feature xml files and geo xml file
    features_path = os.path.join(data_home, "010_manannot", "features")
    geo_data = os.path.join(data_home, "010_manannot", "vicav_geodata.xml")
    bibl_data = os.path.join(data_home, "010_manannot", "vicav_biblio_tei_zotero.xml")

    # Process feature xml files
    documents, processing_errors = process_files(features_path)
    # Extract unique combinations of place and variety, get feature names and parent categories
    place_variety, ft_name_dict, parent_categories = first_pass_features(documents)

    # Read geo data
    geo_doc = TeiReader(geo_data)

    # Get basic geo data
    geo_features = get_geo_info(place_variety, geo_doc)

    # Read bibl data
    bibl_doc = TeiReader(bibl_data)

    # Get basic bibl data
    bibl_data = get_bibl_data(bibl_doc)

    # Add linguistic feature data to geo data
    enriched_features, f_names_count = get_feature_data(
        geo_features, documents, bibl_data
    )

    # We want to sort the feature column headings by the number of feature entries in the DB
    sorted_titles = {
        key: ft_name_dict[key]
        for key in sorted(
            ft_name_dict, key=lambda x: f_names_count.get(x, 0), reverse=True
        )
    }
    # Create list of all column headings (name, variety and all features)
    column_headings = [{"name": "Name"}, {"variety": "Variety"}] + [
        {key: value, "count": f_names_count[key], "category": parent_categories[key]}
        for key, value in sorted_titles.items()
    ]

    # Write everything to GeoJSON file
    geojson_data = {
        "type": "FeatureCollection",
        "properties": {
            "description": "GEOJSON for the WIBARAB Feature DB",
            "column_headings": column_headings,
        },
        "features": enriched_features,
    }
    write_geojson("wibarab_varieties.geojson", geojson_data)

    # Print errors encountered during processing
    if processing_errors:
        print("Processing errors:")
        for error in processing_errors:
            print(error)


if __name__ == "__main__":
    main()
