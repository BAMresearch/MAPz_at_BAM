/*
  Compile ChemTagger with Maven into single jar file with dependencies:
    mvn clean compile assembly:single
  Compile this file together with the ChemTagger jar file:
    javac -cp .;chemicalTagger-1.6-SNAPSHOT-jar-with-dependencies.jar RunChemicalTagger.java
  Run this script (increase heap space with command line option -Xmx1024m):
    java -Xmx1024m -cp .;chemicalTagger-1.6-SNAPSHOT-jar-with-dependencies.jar RunChemicalTagger "InputFile.txt" "OutputFile.xml"
*/

import uk.ac.cam.ch.wwmm.chemicaltagger.POSContainer;
import uk.ac.cam.ch.wwmm.chemicaltagger.ChemistryPOSTagger;
import uk.ac.cam.ch.wwmm.chemicaltagger.ChemistrySentenceParser;
import uk.ac.cam.ch.wwmm.chemicaltagger.Utils;
import nu.xom.Document;

import java.io.*;
import java.util.Scanner;

public class RunChemicalTagger {

   public static void main(String[] args) throws IOException {
	  POSContainer posContainer = null;
	  ChemistrySentenceParser chemistrySentenceParser = null;
	  Document doc = null;
	  String result = "";
      String line = null;
	  Boolean firstLine = true;
	  
	  FileInputStream fis = new FileInputStream(args[0]);
	  Scanner sc = new Scanner(fis, "UTF-8");

	  FileOutputStream fos = new FileOutputStream(args[1]);
	  OutputStreamWriter w = new OutputStreamWriter(fos, "UTF-8");
	  BufferedWriter bw = new BufferedWriter(w);

	  while (sc.hasNextLine()) {
	      line = sc.nextLine();
		  // note that Scanner suppresses exceptions
		  if (sc.ioException() != null) {
			throw sc.ioException();
		  }
		  
		  if (line.split(" ").length > 256) {
			  continue;
		  }

		  chemistrySentenceParser = new ChemistrySentenceParser(ChemistryPOSTagger.getDefaultInstance().runTaggers(line));

		  // Create a parseTree of the tagged input
		  chemistrySentenceParser.parseTags();

		  // Return an XMLDoc
		  doc = chemistrySentenceParser.makeXMLDocument();
		  
		  // Convert to String
		  result = doc.toXML();
		  
		  result = result.replace("Document>", "Reaction>");
		  if (!firstLine) {
			result = result.replace("<?xml version=\"1.0\"?>", "");
		  } else {
			result = result.replace("<?xml version=\"1.0\"?>", "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<Document>");
			firstLine = false;
		  }
		  
		  // Append to file
		  bw.append(result);
	  }
	  bw.append("</Document>");
	  bw.close();
	  w.close();
	  fos.close();
	  fis.close();  
   }
}