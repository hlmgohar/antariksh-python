import os
import fitz  # PyMuPDF for PDF text extraction
import pytesseract
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .serializers import FileUploadSerializer
from PIL import Image
from io import BytesIO
import csv
import openpyxl
from docx import Document
import spacy
import cv2
import numpy as np
import camelot  # For extracting tables

# Mapping of language codes to spaCy models
LANGUAGE_MODELS = {
    'eng': 'en_core_web_sm',    # English
    'ara': 'xx_ent_wiki_sm',    # Arabic (multilingual model)
    'tur': 'xx_ent_wiki_sm',    # Turkish (multilingual model)
    'deu': 'de_core_news_sm',   # German
    'chi_sim': 'zh_core_web_sm' # Chinese Simplified
    # Add more languages as needed
}

# Function to dynamically load spaCy model based on language code
def load_spacy_model(language_code):
    model_name = LANGUAGE_MODELS.get(language_code)
    if model_name:
        nlp = spacy.load(model_name)
        
        # Add the sentencizer if the model does not have a sentence parser
        if not nlp.has_pipe('parser') and not nlp.has_pipe('sentencizer'):
            nlp.add_pipe('sentencizer')
        return nlp
    else:
        # If the language is not supported, return the default English model
        nlp = spacy.load('en_core_web_sm')
        return nlp

# Function to split text into sentences using spaCy
def split_sentences_spacy(text, language_code):
    # Load the appropriate spaCy model
    nlp = load_spacy_model(language_code)
    doc = nlp(text)
    sentences = [sent.text.strip() for sent in doc.sents]
    return sentences

# Function to handle image OCR
def extract_text_from_image_with_cv2(image_bytes, language_code):
    img_array = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # Apply thresholding to improve OCR results
    _, binary_img = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
    
    extracted_text = pytesseract.image_to_string(binary_img)
    sentences = split_sentences_spacy(extracted_text, language_code)
    
    return sentences

# Enhanced function to handle PDF extraction, including embedded images and tables
def extract_text_from_pdf(file_path, language_code):
    extracted_data = []
    document = fitz.open(file_path)
    
    for page_num, page in enumerate(document):
        # Extract text from the page
        extracted_text = page.get_text("text")
        
        # Check for table extraction using Camelot
        tables = camelot.read_pdf(file_path, pages=str(page_num + 1))
        if tables:
            for table in tables:
                extracted_data.append({'table': table.df.to_dict()})

        # Fallback to OCR for embedded images if no text is found
        if not extracted_text.strip():
            pix = page.get_pixmap()
            image_bytes = pix.tobytes("png")
            sentences = extract_text_from_image_with_cv2(image_bytes, language_code)
            for sentence in sentences:
                extracted_data.append({'originalText': sentence.strip()})
        else:
            # Use spaCy to split sentences
            sentences = split_sentences_spacy(extracted_text, language_code)
            for sentence in sentences:
                extracted_data.append({'originalText': sentence.strip()})
    
    document.close()
    return extracted_data

def extract_text_from_docx(file_path, language_code):
    # Load the .docx document
    doc = Document(file_path)
    
    # Extract all text from the docx file
    full_text = []
    for para in doc.paragraphs:
        full_text.append(para.text)
    
    # Combine paragraphs into a single text
    combined_text = '\n'.join(full_text)
    
    # Split text into sentences using spaCy
    sentences = split_sentences_spacy(combined_text, language_code)
    
    # Return the extracted sentences
    extracted_data = [{'originalText': sentence.strip()} for sentence in sentences]
    return extracted_data

def extract_text_from_csv(file_path, language_code):
    extracted_data = []
    
    # Open the CSV file and read its content
    with open(file_path, mode='r', encoding='utf-8') as file:
        csv_reader = csv.reader(file)
        all_text = []
        
        # Read each row and combine all rows into a single text string
        for row in csv_reader:
            all_text.append(' '.join(row))
    
    # Combine all rows into one large string
    combined_text = ' '.join(all_text)
    
    # Split the combined text into sentences using spaCy
    sentences = split_sentences_spacy(combined_text, language_code)
    
    # Return the extracted sentences
    extracted_data = [{'originalText': sentence.strip()} for sentence in sentences]
    return extracted_data

def extract_text_from_excel(file_path, language_code):
    extracted_data = []
    
    # Load the workbook and read the active sheet
    workbook = openpyxl.load_workbook(file_path)
    sheet = workbook.active
    
    # Extract all text from the sheet
    all_text = []
    for row in sheet.iter_rows(values_only=True):
        # Combine all cell values in the row into a single string
        all_text.append(' '.join([str(cell) for cell in row if cell is not None]))
    
    # Combine all rows into a single text string
    combined_text = ' '.join(all_text)
    
    # Split the combined text into sentences using spaCy
    sentences = split_sentences_spacy(combined_text, language_code)
    
    # Return the extracted sentences
    extracted_data = [{'originalText': sentence.strip()} for sentence in sentences]
    return extracted_data


@api_view(['POST'])
def upload_file(request):
    serializer = FileUploadSerializer(data=request.data)
    if serializer.is_valid():
        file = serializer.validated_data['file']
        language_code = request.data.get('language')  # Get language from request body
        
        if not language_code:
            return Response({'error': 'Language not provided'}, status=status.HTTP_400_BAD_REQUEST)

        # Save the file temporarily
        temp_file_path = os.path.join('tmp', file.name)
        with open(temp_file_path, 'wb+') as f:
            for chunk in file.chunks():
                f.write(chunk)

        response_data = []

        # Determine the file type and extract text accordingly
        try:
            if file.name.lower().endswith('.pdf'):
                response_data = extract_text_from_pdf(temp_file_path, language_code)
            elif file.name.lower().endswith(('.png', '.jpg', '.jpeg')):
                with open(temp_file_path, 'rb') as image_file:
                    image_bytes = image_file.read()
                    extracted_data = []
                sentences = extract_text_from_image_with_cv2(image_bytes, language_code)
                for sentence in sentences:
                    extracted_data.append({'originalText': sentence.strip()})
                response_data= extracted_data
            elif file.name.lower().endswith('.docx'):
                response_data = extract_text_from_docx(temp_file_path, language_code)
            elif file.name.lower().endswith('.csv'):
                response_data = extract_text_from_csv(temp_file_path, language_code)
            elif file.name.lower().endswith('.xlsx'):
                response_data = extract_text_from_excel(temp_file_path, language_code)
            else:
                return Response({'error': 'Unsupported file type.'}, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        finally:
            # Clean up the temporary file
            os.remove(temp_file_path)

        return Response(response_data, status=status.HTTP_200_OK)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    