from acdh_tei_pyutils.tei import TeiReader
from pathlib import Path
import os
import json
import re
import csv

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
    Extract unique combinations of places (and associated varieties) from the feature files.
    Get the feature name and parent category for each feature.
    """
    # place_variety_combinations = set()
    mentioned_places = set()
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
                # Add the place_id to the set of mentioned places
                mentioned_places.add(place_id)

    return mentioned_places, ft_name_dict, parent_categories


def get_geo_info(places, geo_doc):
    """
    Get basic geographical information for each mentioned place from the geo data XML file.
    """
    geo_features = []
    # for place_id, variety in place_variety_combinations:
    # if place_id:
    for place_id in places:
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
            # Create feature with place_id and name
            feature = {
                "type": "Feature",
                "id": f"{place_id}",
                "geometry": {"type": "Point", "coordinates": lng_lat},
                "properties": {"name": name},
            }
            geo_features.append(feature)
    geo_features.sort(key=lambda feature: feature["id"])
    return geo_features


def get_variety_titles(profiles):
    variety_title = {}
    for variety_id, doc in profiles.items():
        # Remove unnecessary parts from the variety id
        variety_id = variety_id.split("\\")[-1].split("_")[-1].replace(".xml", "")
        # Get the title from the document
        title = doc.create_plain_text(doc.any_xpath(".//tei:titleStmt/tei:title")[0])
        title = title.replace("A machine-readable profile of", "").strip()
        # Update the dictionary with the short id and title
        variety_title.update({variety_id: title})
    return variety_title


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


def get_pers_data(pers_doc):
    pers_data = {}
    for pers_list in pers_doc.any_xpath("//tei:listPerson"):
        for group in pers_list.findall("./tei:personGrp", namespaces=nsmap):
            group_id = group.get("{http://www.w3.org/XML/1998/namespace}id")
            group_role = group.get("role")
            group_name = group.xpath("./tei:name/text()", namespaces=nsmap)[0]
            pers_data.setdefault(group_role, {})
            pers_data[group_role].update({group_id: group_name})
    return pers_data


def extract_notes(fvo, note_type, fv_entry, key):
    notes = fvo.findall(f'./tei:note[@type="{note_type}"]', namespaces=nsmap)
    valid_notes = [x.text for x in notes if x.text and x.text.strip()]
    if valid_notes:
        fv_entry[key] = valid_notes

def replace_double_quotes(text):
    # Replace straight double quotes with typographic quotes, alternating between opening and closing
    result = []
    open_quote = True
    for char in text:
        if char == '"':
            result.append('“' if open_quote else '”')
            open_quote = not open_quote
        else:
            result.append(char)
    return ''.join(result)

def get_feature_data(geo_features, documents, bibl_data, pers_data, variety_title, team_data):
    """
    Get all linguistic feature data for each place from the XML documents.
    """
    f_names_count = {}
    for feature in geo_features:
        place_id = feature["id"]
        place_xpath = f'//tei:placeName[@ref="{place_id}"]'
        fvo_xpath = f'//wib:featureValueObservation[tei:placeName[@ref="{place_id}"]]'
        # Create dictionary to store the features and their values documented for the current place
        documented_features = {}
        for doc in documents.values():
            # Match the place_id
            if doc.any_xpath(place_xpath):
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
                    # Skip everythin unless status is "done"
                    if fvo.get("status") != "done":
                        continue

                    # Get & add mandatory information for fvos first (based on ODD)
                    fvo_id = fvo.get("{http://www.w3.org/XML/1998/namespace}id")

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
                    fv_entry = {}
                    # get the responsible person
                    resp = fvo.get("resp")
                    if resp and resp.startswith("dmp:"):
                        resp = resp.replace("dmp:", "")
                        if resp in team_data:
                            resp = team_data[resp]
                        else:
                            print("Missing data for resp", resp)
                    else:
                        print("Unknown resp format:", resp)
                    fv_entry["resp"] = resp if resp else "Unknown"

                    # handling of sources
                    fv_entry["source"] = {}
                    source_elems = fvo.findall("./tei:bibl", namespaces=nsmap)
                    if source_elems:
                        # there should be only one source per feature value observation
                        if len(source_elems) > 1:
                            print(
                                f"More than one source in featureValueObservation {fvo_id} in {ft_id}"
                            )
                        ref = source_elems[0].get("corresp")
                        if ref:
                            if ref.startswith("zot:"):
                                bibl_id = ref.replace("zot:", "")
                                if bibl_id:
                                    if bibl_id in bibl_data:
                                        # WATCHME maybe iclude the biblid, but we don't need it rn
                                        fv_entry["source"] = bibl_data[bibl_id]
                                    else:
                                        print(
                                            "Missing source data for",
                                            bibl_id,
                                            ref,
                                        )
                            elif ref.startswith("src:"):
                                bibl_id = ref.replace("src:", "")
                                # Placeholder for sources not in Zotero
                                fv_entry["source"] = {
                                    "short_cit": bibl_id,
                                    "link": "",
                                    "decade_dc": {"2020s": "high"},
                                }
                            else:
                                print("Unknown source reference format:", ref)
                    # Add the variety (ODD only allows one variety per feature value observation)
                    varieties = fvo.findall("./tei:lang", namespaces=nsmap)
                    if varieties:
                        if len(varieties) > 1:
                            print(
                                f"Multiple varieties found for {fvo_id} in {ft_id}:",
                                [x.get("corresp") for x in varieties],
                            )
                        variety_ids = [
                            x.get("corresp")
                            .split("\\")[-1]
                            .split("_")[-1]
                            .replace(".xml", "")
                            for x in varieties
                            if x.get("corresp") is not None
                        ]
                        if variety_ids:
                            try:
                                variety_name = variety_title[variety_ids[0]]
                                fv_entry["variety"] = variety_name
                            except KeyError:
                                print("Missing title for variety", variety_ids[0])
                                fv_entry["variety"] = "Missing"

                    # Get & add other optional elements (based on ODD)
                    # Person group
                    pers_group = fvo.findall("./tei:personGrp", namespaces=nsmap)
                    if pers_group:
                        for x in pers_group:
                            role = x.get("role")
                            corresp = x.get("corresp")
                            if role and corresp:
                                if corresp.startswith("pgr:"):
                                    # Handle cases where corresp starts with "pgr:"
                                    corresp = corresp.replace("pgr:", "")
                                    pers_group_name = pers_data.get(role, {}).get(
                                        corresp
                                    )
                                    if pers_group_name is None:
                                        print(
                                            "Couldn't find matching data for",
                                            role,
                                            corresp,
                                        )
                                else:
                                    # Handle unknown formats
                                    print(
                                        "Unknown person group reference format:",
                                        corresp,
                                        role,
                                    )
                                    pers_group_name = ""

                                fv_entry.setdefault(role, []).append(pers_group_name)

                    # Source representation
                    src_reps = fvo.findall(
                        './tei:cit[@type="sourceRepresentation"]/tei:quote',
                        namespaces=nsmap,
                    )
                    valid_src_reps = [
                        x.text for x in src_reps if x.text and x.text.strip()
                    ]
                    if valid_src_reps:
                        fv_entry["source_representations"] = valid_src_reps

                    # Examples and their translations
                    example_cits = fvo.findall(
                        './tei:cit[@type="example"]', namespaces=nsmap
                    )
                    for cit in example_cits:
                        example_text, translation_text = "", ""
                        quote = cit.find("./tei:quote", namespaces=nsmap)
                        if quote is not None and quote.text and quote.text.strip():
                            example_text = quote.text.strip()
                            example_text= replace_double_quotes(example_text)
                        for transl in cit.findall(
                            './tei:cit[@type="translation"]', namespaces=nsmap
                        ):
                            trans_quote = transl.find("./tei:quote", namespaces=nsmap)
                            if (
                                trans_quote is not None
                                and trans_quote.text
                                and trans_quote.text.strip()
                            ):
                                translation_text = trans_quote.text.strip()
                        if example_text:
                            fv_entry.setdefault("examples", []).append(
                                {example_text: translation_text}
                            )
                    # Notes (they can have the type "general", "constraintNote" or "exceptionNote")
                    types = ["general", "constraintNote", "exceptionNote"]
                    keys = ["remarks", "constraints", "exceptions"]
                    for note_type, key in zip(types, keys):
                        extract_notes(fvo, note_type, fv_entry, key)

                    fv_dict.setdefault(fv_name, []).append(fv_entry)
                    f_names_count[ft_id] = f_names_count.get(ft_id, 0) + 1
                # if fv_name in fv_dict and len(fv_dict[fv_name]) > 1:
                #     print(
                #         f"Multiple feature value observations for {fv_name} in {place_id}:",
                #     )
                if fv_dict:
                    documented_features.update({ft_id: fv_dict})

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
    profiles_path = os.path.join(data_home, "010_manannot", "profiles")
    geo_data = os.path.join(data_home, "010_manannot", "vicav_geodata.xml")
    bibl_data = os.path.join(data_home, "010_manannot", "vicav_biblio_tei_zotero.xml")
    pers_data = os.path.join(data_home, "010_manannot", "wibarab_PersonGroup.xml")
    team_data = os.path.join(data_home, "010_manannot", "wibarab_dmp.xml")

    # Process feature xml files
    documents, processing_errors = process_files(features_path)
    # Process profile xml files
    profiles, processing_errors = process_files(profiles_path)
    variety_title = get_variety_titles(profiles)

    # Process team data
    team_doc = TeiReader(team_data)
    team_data = {}
    team_list  =  team_doc.any_xpath("//tei:listPerson[@xml:id='projectTeam']")[0]
    for person in team_list.findall("./tei:person", namespaces=nsmap):
        pers_id = person.get('{http://www.w3.org/XML/1998/namespace}id')
        pers_name_el = person.find("./tei:persName", namespaces=nsmap)
        if pers_name_el is not None:
            forename = pers_name_el.findtext("tei:forename", default="", namespaces=nsmap)
            surname = pers_name_el.findtext("tei:surname", default="", namespaces=nsmap)
            full_name = f"{forename} {surname}".strip()
            team_data[pers_id] = full_name

    # Extract unique places, get feature names and parent categories
    places, ft_name_dict, parent_categories = first_pass_features(documents)

    # Read geo data
    geo_doc = TeiReader(geo_data)

    # Get basic geo data
    geo_features = get_geo_info(places, geo_doc)

    # Read bibl data
    bibl_doc = TeiReader(bibl_data)

    # Get basic bibl data
    bibl_data = get_bibl_data(bibl_doc)

    # Read person data
    pers_doc = TeiReader(pers_data)

    # Get basic person data
    pers_data = get_pers_data(pers_doc)

    # Add linguistic feature data to geo data
    enriched_features, f_names_count = get_feature_data(
        geo_features, documents, bibl_data, pers_data, variety_title, team_data
    )

    # We want to sort the feature column headings by the number of feature entries in the DB
    sorted_titles = {
        key: ft_name_dict[key]
        for key in sorted(
            ft_name_dict, key=lambda x: f_names_count.get(x, 0), reverse=True
        )
    }
    # Create list of all column headings (name, variety and all features)
    column_headings = [{"name": "Name"}] + [
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
