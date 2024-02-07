from acdh_tei_pyutils.tei import TeiReader
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
    processed_data = []
    errors = set()
    for file_name in os.listdir(directory):
        file_path = os.path.join(directory, file_name)
        if os.path.isfile(file_path) and "template" not in file_name:
            try:
                doc = TeiReader(file_path)
                processed_data.append(doc)
            except (SyntaxError, OSError) as e:
                errors.add(f"Error processing file {file_name}: {e}")
    return processed_data, errors


def get_place_list(documents):
    """
    Extract a unique list of places from the feature files.
    """
    unique_places = set()
    for doc in documents:
        place_names = doc.any_xpath("//tei:placeName/@ref")
        unique_places.update(place_names)
    return unique_places


def get_geo_info(unique_places, geo_doc):
    """
    Get basic geographical information for each place from the geo data XML file.
    """
    geo_features = []
    for place_id in unique_places:
        if place_id:
            geo_xml_id = place_id.split(":")[1]
            location_el = geo_doc.any_xpath(
                f'//tei:place[@xml:id="{geo_xml_id}"]/tei:location'
            )
            if location_el:
                geo_el = location_el[0].find(
                    'tei:geo[@decls="#dd"]', namespaces=nsmap
                )
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
                # NOTE: currently everything is a "Point" regardless of type geo/reg, because we only have point coordinates atp
                feature = {
                    "type": "Feature",
                    "id": place_id,
                    "geometry": {"type": "Point", "coordinates": lng_lat},
                    "properties": {"name": name},
                }
                geo_features.append(feature)
    return geo_features


def get_feature_data(geo_features, documents):
    """
    Get all linguistic feature data for each place from the XML documents.
    """
    for feature in geo_features:
        place_id = feature["id"]
        documented_features = []
        for doc in documents:
            if doc.any_xpath(f'//tei:placeName[@ref="{place_id}"]'):
                title = doc.any_xpath(".//tei:titleStmt/tei:title")[0]
                feature_name = doc.create_plain_text(title)
                fv_list = []
                for fvo in doc.tree.xpath(
                    f'//wib:featureValueObservation[tei:placeName[@ref="{place_id}"]]',
                    namespaces=nsmap,
                ):
                    # Get & add mandatory information for fvos first (based on ODD)
                    fv_name = fvo.find("./tei:name", namespaces=nsmap).get("ref")
                    sources = fvo.findall("./tei:bibl", namespaces=nsmap)
                    sources = [x.get("corresp") for x in sources]
                    feature_value = {"name": fv_name, "sources": sources}
                    # Get & add other optional elements (based on ODD)
                    # Person group
                    pers_group = fvo.findall("./tei:personGrp", namespaces=nsmap)
                    if pers_group:
                        feature_value["person_groups"] = [
                            {x.get("role"): x.get("corresp")} for x in pers_group
                        ]
                    # Variety
                    varieties = fvo.findall("./tei:lang", namespaces=nsmap)
                    if varieties:
                        feature_value["varieties"] = [
                            x.get("corresp") for x in varieties
                        ]
                    # Source representation
                    src_reps = fvo.findall(
                        './tei:cit[@type="sourceRepresentation"]/tei:quote',
                        namespaces=nsmap,
                    )
                    if src_reps:
                        feature_value["source_representations"] = [
                            x.text for x in src_reps
                        ]
                    # Examples
                    examples = fvo.findall(
                        './tei:cit[@type="example"]/tei:quote', namespaces=nsmap
                    )
                    if examples:
                        feature_value["examples"] = [x.text for x in examples]
                    # Notes
                    notes = fvo.findall(
                        './tei:cit[@type="note"]/tei:quote', namespaces=nsmap
                    )
                    if notes:
                        feature_value["notes"] = [x.text for x in notes]
                    fv_list.append(feature_value)
                if fv_list:
                    documented_features.append(
                        {"name": feature_name, "documented_values": fv_list}
                    )
                feature["properties"]["documented_features"] = documented_features
    return geo_features


def write_geojson(output_file, geojson_data):
    with open(output_file, "w") as geojson_file:
        json.dump(geojson_data, geojson_file, indent=2)


def main():
    # Path to the featuredb, adjust if necessary
    data_home = "featuredb"
    # Paths to feature xml files and geo xml file
    features_path = os.path.join(data_home, "010_manannot", "features")
    geo_data = os.path.join(data_home, "010_manannot", "vicav_geodata.xml")

    # Process feature xml files
    documents, processing_errors = process_files(features_path)

    # Extract unique place names
    unique_places = get_place_list(documents)

    # Read geo data
    geo_doc = TeiReader(geo_data)

    # Get basic geo data
    geo_features = get_geo_info(unique_places, geo_doc)

    # Add linguistic feature data to geo data
    enriched_features = get_feature_data(geo_features, documents)

    # Write everything to GeoJSON file
    geojson_data = {
        "type": "FeatureCollection",
        "properties": {"description": "GEOJSON for the WIBARAB Feature DB"},
        "features": enriched_features,
    }
    write_geojson("wibarab.geojson", geojson_data)

    # Print errors encountered during processing
    if processing_errors:
        print("Processing errors:")
        for error in processing_errors:
            print(error)


if __name__ == "__main__":
    main()
