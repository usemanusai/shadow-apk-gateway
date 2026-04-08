// Synthetic JS file for testing jsasset parser
const API_BASE = 'https://api.example.com';

async function loadProducts() {
    const response = await fetch('https://api.example.com/v1/products');
    return response.json();
}

function createOrder(data) {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/v1/orders');
    xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.send(JSON.stringify(data));
}

const api = axios.create({ baseURL: API_BASE });

function getUser(id) {
    return axios.get('/api/v1/users/' + id);
}

function updateProfile(data) {
    return axios.post('/api/v1/profile', data);
}
