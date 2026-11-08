import { scientificErrorMessage } from './scientificErrors';

test('renders the server policy message without internal identifiers', () => {
  expect(scientificErrorMessage({code:'baseline_limit_exceeded',message:'Превышен предел тарифа',request_id:'private-reference'})).toBe('Превышен предел тарифа');
});
test('preserves legacy string errors', () => {
  expect(scientificErrorMessage('Сначала загрузите датасет')).toBe('Сначала загрузите датасет');
});
test('does not stringify validation inputs or arbitrary response objects', () => {
  expect(scientificErrorMessage({input:{password:'not-for-render'}})).toBeNull();
  expect(scientificErrorMessage([{msg:'validation',input:'secret'}])).toBeNull();
});
test('empty and malformed messages use the caller fallback', () => {
  for(const value of [null,undefined,17,{message:17},{message:' '},'']) expect(scientificErrorMessage(value)).toBeNull();
});
